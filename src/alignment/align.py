import time

from diversity.task2vec import Task2Vec 
from diversity import task_similarity

from pathlib import Path

import torch
import torch.nn as nn

# def alginment_with_diversity_coefficient(dataset_target,
#                                         dataset_source,
#                                         get_mapped_batch_fn: callable, 
#                                         probe_network: nn.Module,
#                                         tokenizer = None,
#                                         batch_size: int = 512,
#                                         num_batches: int = 100, 
#                                         seed = 0, 
#                                         buffer_size: int = 500_000, 
#                                         distance = 'cosine',
#                           ) -> dict:
#     """
#     Alignment v1 - with the Diversity Coefficient
    
#     Given two data sets, compute how aligned they are using probe network f_w by comparing batches across the data sets:
#         alg1 = align(T, S, f_w) = Align_1(T, S, f_w) = E_{B_s ~ S, B_t ~ T} [1 - d(e_{B_s}, e_{B_t})] =  1 - div(T, S)
#     where e_{D} is the Task2Vec (diagonal of FIM) embedding of a batch D, and d is cosine distance function.
    
#     ref: https://arxiv.org/abs/2306.13840
#     """
#     results: dict = cross_diversity_coefficient(dataset_target, dataset_source, get_mapped_batch_fn, probe_network, tokenizer, batch_size, num_batches, seed, buffer_size, distance)
#     results['align'] = 1 - results['div_coeff']
#     results['align_ci'] = results['div_coeff_ci']
#     return results


def alignment_task2vec(dataset_target,
                        dataset_source,
                        map_target: callable,
                        map_source: callable,
                        probe_network: nn.Module,
                        tokenizer = None,
                        batch_size: int = 1024,
                        seed = 0, 
                        buffer_size: int = 500_000, 
                        distance = 'cosine',
                        verbose: bool = False,
                        debug: bool = False,
                        ) -> dict:
    """
    Alignment v2 - with Task2Vec

    Given two data sets, compute how aligned they are using probe network f_w 
        alg_2 = Align_2(T, S, f_w) = 1 - d(e_{D_S}, e_{D_T})
    by comparing embedding the entire dataset or a large batch. 

    Note: there is no sense of number of batches here, so num_batches = 1 effectively + if CIs needed need to be with wrt batch examples. 
    """
    # - Get target shuffled data
    shuffled_dataset = dataset_target.shuffle(buffer_size=buffer_size, seed=seed)
    # raw_text_batch = shuffled_dataset.take(batch_size)
    raw_text_batch = dataset_target.take(batch_size)
    tokenized_batch = map_target(raw_text_batch)

    if verbose:
        print(f'{raw_text_batch=}')
        print(f'{tokenized_batch=}')
        # time_start = time.time()
        # really slow with suffle it seems
        # print(f'{next(iter(raw_text_batch))=}')
        # print(f'{next(iter(tokenized_batch))=}')
        # print(f'Time it took: {time.time() - time_start} seconds \a\n')
    
    # - Get Task2Vec embedding for batch
    if not debug:
        embedding_target, loss_target = Task2Vec(probe_network).embed(tokenized_batch)
    else:
        embedding_target, loss_target = Task2Vec(probe_network, classifier_opts={'break_early': True}).embed(tokenized_batch, epochs=1)  # only for debugging
    print(f'{loss_target=}\n{embedding_target=}\n') if verbose else None

    # - Get source shuffled data
    shuffled_dataset = dataset_source.shuffle(buffer_size=buffer_size, seed=seed)
    raw_text_batch = shuffled_dataset.take(batch_size)
    tokenized_batch = map_source(raw_text_batch)
    
    # - Get Task2Vec embedding for batch
    if not debug:
        embedding_source, loss_source = Task2Vec(probe_network).embed(tokenized_batch, epochs=1)
    else:
        embedding_source, loss_source = Task2Vec(probe_network, classifier_opts={'break_early': True}).embed(tokenized_batch, epochs=1)  # only for debugging
    print(f'{loss_target=}\n{embedding_target=}\n') if verbose else None

    # - Compute results
    embeddings, losses = [], []
    embeddings.append({'embedding_target': embedding_target, 'embedding_source': embedding_source})
    losses.append({'loss_target': loss_target, 'loss_source': loss_source})
    
    # - Compute alignment
    distance_matrix = task_similarity.pdist([embedding_target, embedding_source], distance=distance)
    align = 1 - distance_matrix[0, 1]
    align_ci = task_similarity.stats_of_distance_matrix(distance_matrix)[1]

    # - Results
    results: dict = {'align': align, 'align_ci': align_ci,
                    'embeddings': embeddings,
                    'distance_matrix': distance_matrix,
                    'losses': losses,
                    "batch_size": batch_size}
    return results
    
# - Tests, examples

def test_get_batch_from_dataset():
    batch_size = 10
    token = None

    from transformers import GPT2Tokenizer, GPT2LMHeadModel
    tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
    if tokenizer.pad_token_id is None:
      tokenizer.pad_token = tokenizer.eos_token

    # -- Get batch from dataset
    from datasets import load_dataset
    # path, name = 'brando/debug0_autoformalization', 'debug0_autoformalization'
    # https://huggingface.co/datasets/brando/debug1_af
    path, name = 'brando/debug1_af', 'debug1_af'
    # path, name = 'c4', 'en'
    # path, name = "wikitext", 'wikitext-103-v1'
    # path, name = Path('~/data-quality/debug_data/debug_data_15_examples_round_trip/RoundTripNthPowersData_Sheet1.csv').expanduser(), None
    dataset = load_dataset(path, name, streaming=True, split="train").with_format("torch")

    # - Gets a raw text batch
    batch = dataset.take(batch_size)
    print(f'{batch=}')
    print(f'{next(iter(batch))=}')
    print(f'{list(batch)[0]=}')

    # - Tokenize text batch
    def preprocess(examples):
        return tokenizer(examples["informal"], padding="max_length", max_length=256, truncation=True, return_tensors="pt")
    batch = batch.map(preprocess, batched=True, remove_columns=[])
    print(f'{batch=}')
    print(f'{next(iter(batch))=}')
    print()

def get_tokenized_dataset_to_work_with_pytorch_dataloader_by_removing_columns_without_tenosr():
    """
    Remove the columns that are not tensors, and then it works with pytorch dataloader.

    ref so: https://stackoverflow.com/questions/76872115/how-does-one-create-a-pytorch-data-loader-with-a-custom-hugging-face-data-set-wi
    """
    batch_size = 10
    token = open(Path('~/data/hf_token.txt').expanduser()).read().strip()

    # -- AF now
    from datasets import load_dataset
    import torch
    from transformers import GPT2Tokenizer, GPT2LMHeadModel
    
    tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
    if tokenizer.pad_token_id is None:
      tokenizer.pad_token = tokenizer.eos_token
    probe_network = GPT2LMHeadModel.from_pretrained("gpt2")
    device = torch.device(f"cuda:{0}" if torch.cuda.is_available() else "cpu")
    probe_network = probe_network.to(device)

    # -- Get batch from dataset
    from datasets import load_dataset
    path, name = 'brando/debug1_af', 'debug1_af'
    dataset = load_dataset(path, name, streaming=True, split="train", token=token).with_format(type="torch")
    print(f'{dataset.column_names=}')
    batch = dataset.take(1)
    def preprocess_formalize(examples): 
        """ link,formal statement,generated informal statement,solvable by sledgehammer,keep or not,informalization correct """
        informal_statement = examples["generated informal statement"]
        formal_statement = examples["formal statement"]
        text = f'informal statement {informal_statement} formal statement {formal_statement}'
        return tokenizer(text, padding="max_length", max_length=128, truncation=True, return_tensors="pt")
    column_names = next(iter(batch)).keys()
    print(f'{column_names=}')

    # - Prepare functions to tokenize batch
    preprocess = preprocess_formalize
    remove_columns = column_names  # remove everything except the tokenized fields in the dict
    print(f'{remove_columns=}')
    def map(batch):  # apply preprocess to batch to all examples in batch represented as a dataset
        return batch.map(preprocess, batched=True, remove_columns=remove_columns)
    tokenized_batch = map(batch)

    # -- Get data loader
    from torch.utils.data import DataLoader, Dataset
    data_loader = DataLoader(tokenized_batch, shuffle=False, batch_size=64, num_workers=0, drop_last=False)
    print(f'{next(iter(data_loader))=}')
    print('Done!\a')

def demo_how_to_use_collate_fn_with_pytorch_dataloader():
    """
    I don't think we will need this for task2vec but hopefully this insight helps for passing the collate to the hf trainer. 

    so: https://stackoverflow.com/questions/76872115/how-does-one-create-a-pytorch-data-loader-with-a-custom-hugging-face-data-set-wi
    """
    batch_size = 2048
    token = open(Path('~/data/hf_token.txt').expanduser()).read().strip()

    # -- AF now
    from datasets import load_dataset
    import torch
    from transformers import GPT2Tokenizer, GPT2LMHeadModel
    
    tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
    if tokenizer.pad_token_id is None:
      tokenizer.pad_token = tokenizer.eos_token
    probe_network = GPT2LMHeadModel.from_pretrained("gpt2")
    device = torch.device(f"cuda:{0}" if torch.cuda.is_available() else "cpu")
    probe_network = probe_network.to(device)

    # -- Get batch from dataset
    from datasets import load_dataset
    path, name = 'brando/debug1_af', 'debug1_af'
    dataset = load_dataset(path, name, streaming=True, split="train", token=token).with_format(type="torch")
    batch = dataset.take(batch_size)
    # column_names = next(iterbatch).keys()
    # print(f'{column_names=}')
    
    # -- Get data loader
    from torch.utils.data import DataLoader, Dataset

    def collate_tokenize(data):
        text_batch = [f'informal statement {example["generated informal statement"]} formal statement {example["formal statement"]}' for example in data]
        tokenized = tokenizer(text_batch, padding='longest', max_length=128, truncation=True, return_tensors='pt')
        return tokenized
    data_loader = DataLoader(batch, shuffle=False, batch_size=8, num_workers=0, drop_last=False, collate_fn=collate_tokenize)
    batch = next(iter(data_loader))
    print(f'{batch=}')

    data_loader = DataLoader(dataset, shuffle=False, batch_size=8, num_workers=0, drop_last=False, collate_fn=collate_tokenize)
    batch = next(iter(data_loader))
    print(f'{batch=}')
    print('Done!\a')

def demo_finetuning_gpt2_with_collate_passed_to_trainer_on_af_dataset():
    """
    """
    # token = open(Path('~/data/hf_token.txt').expanduser()).read().strip()
    token = None
    batch_size = 8

    # -- AF now
    from datasets import load_dataset
    import torch
    from transformers import GPT2Tokenizer, GPT2LMHeadModel
    
    tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
    if tokenizer.pad_token_id is None:
      tokenizer.pad_token = tokenizer.eos_token
    model = GPT2LMHeadModel.from_pretrained("gpt2")
    device = torch.device(f"cuda:{0}" if torch.cuda.is_available() else "cpu")
    model = model.to(device)

    # -- Get batch from dataset
    from datasets import load_dataset
    # path, name = 'brando/debug1_af', 'debug1_af'
    path, name = 'brando/debug0_af', 'debug0_af'
    # train_dataset = load_dataset(path, name, streaming=True, split="train", token=token).with_format(type="torch")
    # eval_dataset = load_dataset(path, name, streaming=True, split="test", token=token).with_format(type="torch")
    # batch = dataset.take(1)
    # column_names = next(iterbatch).keys()
    # print(f'{column_names=}')

    # -- Compute max steps (I think we should try to do this for real experiments such that the number of tokens is the same in all training runs for fair experiments, todo: ask Sudharsan or online, for now just make streaming=False)
    train_dataset = load_dataset(path, name, streaming=False, split="train", token=token).with_format(type="torch")  # hack to get dataset size
    eval_dataset = load_dataset(path, name, streaming=False, split="test", token=token).with_format(type="torch") # hack to get dataset size
    print(f'{len(train_dataset)=}')
    print(f'{len(eval_dataset)=}')
    per_device_train_batch_size = batch_size
    num_epochs = 1
    max_steps = (len(train_dataset) // per_device_train_batch_size) * num_epochs
    print(f'{max_steps=}')    

    # -- Get trainer
    def collate_tokenize(data):
        text_batch = [f'informal statement {example["generated informal statement"]} formal statement {example["formal statement"]}' for example in data]
        tokenized = tokenizer(text_batch, padding='longest', max_length=128, truncation=True, return_tensors='pt')
        return tokenized

    from transformers import Trainer, TrainingArguments
    training_args = TrainingArguments(
        output_dir=Path('~/data/results/af_debug').expanduser(),          # output directory
        max_steps=max_steps,             # max_steps
        per_device_train_batch_size=batch_size,   # batch size per device during training
        per_device_eval_batch_size=batch_size,    # batch size for evaluation
        warmup_steps=500,                # number of warmup steps for learning rate scheduler
        weight_decay=0.01,               # strength of weight decay
        logging_dir=Path('~/data/logs/af_debug').expanduser(),            # directory for storing logs
        logging_steps=10,
        report_to='none',
    )
    trainer = Trainer(
        model=model,                         # the instantiated 🤗 Transformers model to be trained
        args=training_args,                  # training arguments, defined above
        train_dataset=train_dataset,         # training dataset
        eval_dataset=eval_dataset,             # evaluation dataset
        data_collator = collate_tokenize,
    )
    trainer.train()
    print('Done!\a')

# - Experiments

def sanity2_af_is_aligned_to_af():
    """ Sanity check that data from the same place has low. Prev work showed 0.05 is lower bound.
    so hopefully around that number. """
    batch_size = 64
    remove_columns = []
    remove_columns2 = []
    # token = open(Path('~/data/hf_token.txt').expanduser()).read().strip()
    token = None

    # -- Get probe network
    from datasets import load_dataset
    import torch
    from transformers import GPT2Tokenizer, GPT2LMHeadModel
    
    tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
    if tokenizer.pad_token_id is None:
      tokenizer.pad_token = tokenizer.eos_token
    probe_network = GPT2LMHeadModel.from_pretrained("gpt2")
    device = torch.device(f"cuda:{0}" if torch.cuda.is_available() else "cpu")
    probe_network = probe_network.to(device)

    # -- Get batch from dataset
    from datasets import load_dataset
    # path, name = 'brando/debug1_af', 'debug1_af'
    path, name = 'brando/debug0_af', 'debug0_af'
    path2, name2 = 'c4', 'en'
    dataset = load_dataset(path, name, streaming=True, split="train", token=token).with_format(type="torch")
    print(f'{dataset.column_names=}')
    dataset2 = load_dataset(path2, name2, streaming=True, split="train", token=token).with_format(type="torch")
    print(f'{dataset2.column_names=}')
    
    batch = dataset.take(1)
    batch2 = dataset2.take(1)
    
    def preprocess_formalize(examples): 
        """ link,formal statement,generated informal statement,solvable by sledgehammer,keep or not,informalization correct """
        informal_statement = examples["generated informal statement"]
        formal_statement = examples["formal statement"]
        text = f'informal statement {informal_statement} formal statement {formal_statement}'
        return tokenizer(text, padding="max_length", max_length=1024, truncation=True, return_tensors="pt")
    def preprocess_formalize2(examples): 
        """ link,formal statement,generated informal statement,solvable by sledgehammer,keep or not,informalization correct """
        statement = examples["text"]
        text = f'statement {statement}'
        return tokenizer(text, padding="max_length", max_length=1024, truncation=True, return_tensors="pt")
    column_names = next(iter(batch)).keys()
    # column_names = ['link', 'formal statement', 'generated informal statement', 'solvable by sledgehammer', 'keep or not', 'informalization correct']
    # print(f'{column_names=}')
    column_names2 = next(iter(batch2)).keys()

    # - Prepare functions to tokenize batch
    preprocess = preprocess_formalize
    preprocess2 = preprocess_formalize2
    remove_columns = column_names  # remove everything except the tokenized fields in the dict
    remove_columns2 = column_names2
    print(f'{remove_columns=}')
    print(f'{remove_columns2=}')
    def map(batch):  # apply preprocess to batch to all examples in batch represented as a dataset
        return batch.map(preprocess, batched=True, remove_columns=remove_columns)
    tokenized_batch = map(batch)
    def map2(batch):  # apply preprocess to batch to all examples in batch represented as a dataset
        return batch.map(preprocess2, batched=True, remove_columns=remove_columns2)
    tokenized_batch2 = map2(batch2)


    # -- Compute alignment
    print('-- Compute alignment...')
    # results = alignment_task2vec(dataset, dataset, map, map, probe_network, verbose=True, debug=True, batch_size=batch_size)
    results = alignment_task2vec(dataset, dataset2, map, map2, probe_network, verbose=True, debug=False, batch_size=batch_size)
    print(f'{results=}')


if __name__ == '__main__':
    print(f'\n\n\n------------------- Running {__file__} -------------------')
    # -- Run tests and time it
    import time
    time_start = time.time()
    # -- Run tests
    # test_get_batch_from_dataset()
    # get_tokenized_dataset_to_work_with_pytorch_dataloader_by_removing_columns_without_tenosr()
    # demo_how_to_use_collate_fn_with_pytorch_dataloader()
    # demo_finetuning_gpt2_with_collate_passed_to_trainer_on_af_dataset()
    sanity2_af_is_aligned_to_af()
    # -- End tests, report how long it took
    print(f'Time it took: {time.time() - time_start} seconds \a\n')