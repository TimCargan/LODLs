import fcntl
import functools
import inspect
import os
import pandas as pd
import pickle
import torch
from itertools import repeat
from typing import Dict
from io import StringIO
import sys


class Capturing(list):
    """
    Helper to capture stdout when running the opt as it gets messy using cvxpy 1.2
    This will just capture stdout and save it to a list for later use.
    Currently, we just eat it or print it if LOG_OPT_STDOUT is set to True
    """
    def __enter__(self):
        self._stdout = sys.stdout
        sys.stdout = self._stringio = StringIO()
        return self

    def __exit__(self, *args):
        self.extend(self._stringio.getvalue().splitlines())
        del self._stringio    # free up some memory
        sys.stdout = self._stdout


def capture(fn):
    """Wrapper function for capturing stdout when context manager is a pain"""
    @functools.wraps(fn)
    def _fn(*args, **kwargs):
        with Capturing() as output:
            fn_output = fn(*args, **kwargs)
        if os.environ.get("LOG_OPT_STDOUT", False):
            print(output)
        return fn_output

    return _fn


def lock(fn):
    def wrap(*args, **kwargs):
        with open(".lock", "a") as file:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX)
            res = fn(*args, **kwargs)
            # Release the lock
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        return res
    return wrap

@lock
def init_if_not_saved(
    problem_cls,
    kwargs,
    folder='models',
    load_new=True,
):
    # Find the filename if a saved version of the problem with the same kwargs exists
    master_filename = os.path.join(folder, f"{problem_cls.__name__}.csv")
    filename, saved_probs = find_saved_problem(master_filename, kwargs)
    
    print(f"Problem Saved as: {filename}")
 
    if not load_new and filename is not None:
        # Load the model
        with open(filename, 'rb') as file:
            problem = pickle.load(file)
    else:
        # Initialise model from scratch
        problem = problem_cls(**kwargs)

        # Save model for the future
        print("Saving the problem")
        filename = os.path.join(folder, f"{problem_cls.__name__}_{len(saved_probs)}.pkl")
        with open(filename, 'wb') as file:
            pickle.dump(problem, file)

        # Add its details to the master file
        kwargs['filename'] = filename
        saved_probs = pd.concat([saved_probs, pd.DataFrame.from_dict([kwargs])])
        with open(master_filename, 'w') as file:
            saved_probs.to_csv(file, index=False)

    return problem

def find_saved_problem(
    master_filename: str,
    kwargs: Dict,
):
    # Open the master file with details about saved models
    if os.path.exists(master_filename):
        with open(master_filename, 'r') as file:
            saved_probs = pd.read_csv(file)
    else:
        saved_probs = pd.DataFrame(columns=('filename', *kwargs.keys(),))
    
    # Check if the problem has been saved before
    relevant_models = saved_probs
    for col, val in kwargs.items():
        if col in relevant_models.columns:
            relevant_models = relevant_models.loc[relevant_models[col] == val]  # filtering models by parameters

    # If it has, find the relevant filename
    filename = None
    if not relevant_models.empty:
        filename = relevant_models['filename'].values[0]
    
    return filename, saved_probs

def print_metrics(
    datasets,
    model,
    problem,
    loss_type,
    loss_fn,
    prefix="",
):
    # print(f"Current model parameters: {[param for param in model.parameters()]}")
    metrics = {}
    for Xs, Ys, Ys_aux, partition in datasets:
        # Choose whether we should use train or test 
        isTrain = (partition=='train') and (prefix != "Final")

        # Decision Quality
        device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        pred = model(Xs).squeeze().to(device)
        Zs_pred = problem.get_decision(pred, aux_data=Ys_aux, isTrain=isTrain)
        objectives = problem.get_objective(Ys, Zs_pred, aux_data=Ys_aux)

        # Loss and Error
        if partition!='test':
            losses = []
            for i in range(len(Xs)):
                # Surrogate Loss
                pred = model(Xs[i]).squeeze()
                losses.append(loss_fn(pred, Ys[i], aux_data=Ys_aux[i], partition=partition, index=i))
            losses = torch.stack(losses).flatten()
        else:
            losses = torch.zeros_like(objectives)

        # Print
        objective = objectives.mean().item()
        loss = losses.mean().item()
        mae = torch.nn.L1Loss()(losses, -objectives).item()
        print(f"{prefix} {partition} DQ: {objective}, Loss: {loss}, MAE: {mae}")
        metrics[partition] = {'objective': objective, 'loss': loss, 'mae': mae}

    return metrics

def starmap_with_kwargs(pool, fn, args_iter, kwargs):
    args_for_starmap = zip(repeat(fn), args_iter, repeat(kwargs))
    return pool.starmap(apply_args_and_kwargs, args_for_starmap)

def apply_args_and_kwargs(fn, args, kwargs):
    return fn(*args, **kwargs)

def gather_incomplete_left(tensor, I):
    return tensor.gather(I.ndim, I[(...,) + (None,) * (tensor.ndim - I.ndim)].expand((-1,) * (I.ndim + 1) + tensor.shape[I.ndim + 1:])).squeeze(I.ndim)

def trim_left(tensor):
    while tensor.shape[0] == 1:
        tensor = tensor[0]
    return tensor

class View(torch.nn.Module):
    def __init__(self, shape):
        super().__init__()
        self.shape = shape

    def __repr__(self):
        return f'View{self.shape}'

    def forward(self, input):
        '''
        Reshapes the input according to the shape saved in the view data structure.
        '''
        batch_size = input.shape[:-1]
        shape = (*batch_size, *self.shape)
        out = input.view(shape)
        return out

def solve_lineqn(A, b, eps=1e-5):
    try:
        result = torch.linalg.solve(A, b)
    except RuntimeError:
        print(f"WARNING: The matrix was singular")
        result = torch.linalg.solve(A + eps * torch.eye(A.shape[-1]), b)
    return result

def move_to_gpu(problem):
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    for key, value in inspect.getmembers(problem, lambda a:not(inspect.isroutine(a))):
        if isinstance(value, torch.Tensor):
            problem.__dict__[key] = value.to(device)
