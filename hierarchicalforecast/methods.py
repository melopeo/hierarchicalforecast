# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/methods.ipynb (unless otherwise specified).

__all__ = ['bottom_up', 'BottomUp', 'is_strictly_hierarchical', 'top_down', 'TopDown', 'middle_out', 'MiddleOut',
           'crossprod', 'min_trace', 'MinTrace', 'erm', 'ERM']

# Cell
from collections import OrderedDict
from copy import deepcopy
from typing import Dict, List

import numpy as np
from statsmodels.stats.moment_helpers import cov2corr

# Cell
def _reconcile(S: np.ndarray, P: np.ndarray, W: np.ndarray,
               y_hat: np.ndarray, SP: np.ndarray = None):
    if SP is None:
        SP = S @ P
    return np.matmul(SP, y_hat)

# Cell
def bottom_up(S: np.ndarray,
              y_hat: np.ndarray,
              idx_bottom: List[int]):
    n_hiers, n_bottom = S.shape
    P = np.zeros_like(S, dtype=np.float32)
    P[idx_bottom] = S[idx_bottom]
    P = P.T
    W = np.eye(n_hiers, dtype=np.float32)
    return _reconcile(S, P, W, y_hat)

# Cell
class BottomUp:

    def reconcile(self,
                  S: np.ndarray,
                  y_hat: np.ndarray,
                  idx_bottom: np.ndarray):
        return bottom_up(S=S, y_hat=y_hat, idx_bottom=idx_bottom)

    __call__ = reconcile

# Cell
def is_strictly_hierarchical(S: np.ndarray,
                             levels: Dict[str, np.ndarray]):
    # main idea:
    # if S represents a strictly hierarchical structure
    # the number of paths before the bottom level
    # should be equal to the number of nodes
    # of the previuos level
    levels_ = dict(sorted(levels.items(), key=lambda x: len(x[1])))
    # removing bottom level
    levels_.popitem()
    # making S categorical
    hiers = [np.argmax(S[idx], axis=0) + 1 for _, idx in levels_.items()]
    hiers = np.vstack(hiers)
    paths = np.unique(hiers, axis=1).shape[1]
    nodes = levels_.popitem()[1].size
    return paths == nodes

# Cell
def _get_child_nodes(S: np.ndarray, levels: Dict[str, np.ndarray]):
    childs = {}
    level_names = list(levels.keys())
    nodes = OrderedDict()
    for i_level, level in enumerate(level_names[:-1]):
        parent = levels[level]
        child = np.zeros_like(S)
        idx_child = levels[level_names[i_level+1]]
        child[idx_child] = S[idx_child]
        nodes_level = {}
        for idx_parent_node in parent:
            parent_node = S[idx_parent_node]
            idx_node = child * parent_node.astype(bool)
            idx_node, = np.where(idx_node.sum(axis=1) > 0)
            nodes_level[idx_parent_node] = [idx for idx in idx_child if idx in idx_node]
        nodes[level] = nodes_level
    return nodes

# Cell
def _reconcile_fcst_proportions(S: np.ndarray, y_hat: np.ndarray,
                                levels: Dict[str, np.ndarray],
                                nodes: Dict[str, Dict[int, np.ndarray]],
                                idx_top: int):
    reconciled = np.zeros_like(y_hat)
    reconciled[idx_top] = y_hat[idx_top]
    level_names = list(levels.keys())
    for i_level, level in enumerate(level_names[:-1]):
        nodes_level = nodes[level]
        for idx_parent, idx_childs in nodes_level.items():
            fcst_parent = reconciled[idx_parent]
            childs_sum = y_hat[idx_childs].sum()
            for idx_child in idx_childs:
                reconciled[idx_child] = y_hat[idx_child] * fcst_parent / childs_sum
    return reconciled

# Cell
def top_down(S: np.ndarray,
             y_hat: np.ndarray,
             y: np.ndarray,
             levels: Dict[str, np.ndarray],
             method: str):
    if not is_strictly_hierarchical(S, levels):
        raise ValueError('Top down reconciliation requires strictly hierarchical structures.')

    n_hiers, n_bottom = S.shape
    idx_top = int(S.sum(axis=1).argmax())
    levels_ = dict(sorted(levels.items(), key=lambda x: len(x[1])))
    idx_bottom = levels_[list(levels_)[-1]]

    if method == 'forecast_proportions':
        nodes = _get_child_nodes(S=S, levels=levels_)
        reconciled = [_reconcile_fcst_proportions(S=S, y_hat=y_hat_[:, None],
                                                  levels=levels_,
                                                  nodes=nodes,
                                                  idx_top=idx_top) \
                      for y_hat_ in y_hat.T]
        reconciled = np.hstack(reconciled)
        return reconciled
    else:
        y_top = y[idx_top]
        y_btm = y[idx_bottom]
        if method == 'average_proportions':
            prop = np.mean(y_btm / y_top, axis=1)
        elif method == 'proportion_averages':
            prop = np.mean(y_btm, axis=1) / np.mean(y_top)
        else:
            raise Exception(f'Unknown method {method}')
    P = np.zeros_like(S, np.float64).T #float 64 if prop is too small, happens with wiki2
    P[:, idx_top] = prop
    W = np.eye(n_hiers, dtype=np.float32)
    return _reconcile(S, P, W, y_hat)

# Cell
class TopDown:

    def __init__(self, method: str):
        self.method = method

    def reconcile(self,
                  S: np.ndarray,
                  y_hat: np.ndarray,
                  y: np.ndarray,
                  levels: Dict[str, np.ndarray],):
        return top_down(S=S, y_hat=y_hat, y=y,
                        levels=levels,
                        method=self.method)

    __call__ = reconcile

# Cell
def middle_out(S: np.ndarray,
               y_hat: np.ndarray,
               y: np.ndarray,
               levels: Dict[str, np.ndarray],
               level: str,
               top_down_method: str):
    if not is_strictly_hierarchical(S, levels):
        raise ValueError('Middle out reconciliation requires strictly hierarchical structures.')
    if level not in levels.keys():
        raise ValueError('You have to provide a `level` in `levels`.')
    levels_ = dict(sorted(levels.items(), key=lambda x: len(x[1])))
    reconciled = np.full_like(y_hat, fill_value=np.nan)
    cut_nodes = levels_[level]
    # bottom up reconciliation
    idxs_bu = []
    for node, idx_node in levels_.items():
        idxs_bu.append(idx_node)
        if node == level:
            break
    idxs_bu = np.hstack(idxs_bu)
    #bottom up forecasts
    bu = bottom_up(S=np.unique(S[idxs_bu], axis=1),
                   y_hat=y_hat[idxs_bu],
                   idx_bottom=np.arange(len(idxs_bu))[-len(cut_nodes):])
    reconciled[idxs_bu] = bu

    #top down
    child_nodes = _get_child_nodes(S, levels_)
    # parents contains each node in the middle out level
    # as key. The values of each node are the levels that
    # are conected to that node.
    parents = {node: {level: np.array([node])} for node in cut_nodes}
    level_names = list(levels_.keys())
    for lv, lv_child in zip(level_names[:-1], level_names[1:]):
        # if lv is not part of the middle out to bottom
        # structure we continue
        if lv not in list(parents.values())[0].keys():
            continue
        for idx_middle_out in parents.keys():
            idxs_parents = parents[idx_middle_out].values()
            complete_idxs_child = []
            for idx_parent, idxs_child in child_nodes[lv].items():
                if any(idx_parent in val for val in idxs_parents):
                    complete_idxs_child.append(idxs_child)
            parents[idx_middle_out][lv_child] = np.hstack(complete_idxs_child)

    for node, levels_node in parents.items():
        idxs_node = np.hstack(list(levels_node.values()))
        S_node = S[idxs_node]
        S_node = S_node[:,~np.all(S_node == 0, axis=0)]
        counter = 0
        levels_node_ = deepcopy(levels_node)
        for lv_name, idxs_level in levels_node_.items():
            idxs_len = len(idxs_level)
            levels_node_[lv_name] = np.arange(counter, idxs_len + counter)
            counter += idxs_len
        td = top_down(S_node,
                      y_hat[idxs_node],
                      y[idxs_node],
                      levels_node_,
                      method=top_down_method)
        reconciled[idxs_node] = td
    return reconciled


# Cell
class MiddleOut:

    def __init__(self, level: str, top_down_method: str):
        self.level = level
        self.top_down_method = top_down_method

    def reconcile(self,
                  S: np.ndarray,
                  y_hat: np.ndarray,
                  y: np.ndarray,
                  levels: Dict[str, np.ndarray],):
        return middle_out(S=S, y_hat=y_hat, y=y,
                          levels=levels,
                          level=self.level,
                          top_down_method=self.top_down_method)

    __call__ = reconcile

# Cell
def crossprod(x):
    return x.T @ x

# Cell
def min_trace(S: np.ndarray,
              y_hat: np.ndarray,
              residuals: np.ndarray,
              method: str):
    # shape residuals (obs, n_hiers)
    res_methods = ['wls_var', 'mint_cov', 'mint_shrink']
    if method in res_methods and residuals is None:
        raise ValueError(f"For methods {', '.join(res_methods)} you need to pass residuals")
    n_hiers, n_bottom = S.shape
    if method == 'ols':
        W = np.eye(n_hiers)
    elif method == 'wls_struct':
        W = np.diag(S @ np.ones((n_bottom,)))
    elif method in res_methods:
        n, _ = residuals.shape
        masked_res = np.ma.array(residuals, mask=np.isnan(residuals))
        covm = np.ma.cov(masked_res, rowvar=False, allow_masked=True).data
        if method == 'wls_var':
            W = np.diag(np.diag(covm))
        elif method == 'mint_cov':
            W = covm
        elif method == 'mint_shrink':
            tar = np.diag(np.diag(covm))
            corm = cov2corr(covm)
            xs = np.divide(residuals, np.sqrt(np.diag(covm)))
            xs = xs[~np.isnan(xs).any(axis=1), :]
            v = (1 / (n * (n - 1))) * (crossprod(xs ** 2) - (1 / n) * (crossprod(xs) ** 2))
            np.fill_diagonal(v, 0)
            corapn = cov2corr(tar)
            d = (corm - corapn) ** 2
            lmd = v.sum() / d.sum()
            lmd = max(min(lmd, 1), 0)
            W = lmd * tar + (1 - lmd) * covm
    else:
        raise ValueError(f'Unkown reconciliation method {method}')

    eigenvalues, _ = np.linalg.eig(W)
    if any(eigenvalues < 1e-8):
        raise Exception(f'min_trace ({method}) needs covariance matrix to be positive definite.')

    R = S.T @ np.linalg.inv(W)
    P = np.linalg.inv(R @ S) @ R

    return _reconcile(S, P, W, y_hat)

# Cell
class MinTrace:

    def __init__(self, method: str):
        self.method = method

    def reconcile(self,
                  S: np.ndarray,
                  y_hat: np.ndarray,
                  residuals: np.ndarray):
        return min_trace(S=S, y_hat=y_hat,
                         residuals=residuals,
                         method=self.method)

    __call__ = reconcile

# Cell
def erm(S: np.ndarray,
        y_hat: np.ndarray,
        method: str,
        lambda_reg: float = 1e-2):
    n_hiers, n_bottom = S.shape
    if method == 'exact':
        B = y_hat.T @ S @ np.linalg.inv(S.T @ S).T
        P = B.T @ y_hat.T @ np.linalg.inv(y_hat @ y_hat.T + lambda_reg * np.eye(n_hiers))
    else:
        raise ValueError(f'Unkown reconciliation method {method}')

    W = np.eye(n_hiers, dtype=np.float32)

    return _reconcile(S, P, W, y_hat)

# Cell
class ERM:

    def __init__(self, method: str, lambda_reg: float = 1e-2):
        self.method = method
        self.lambda_reg = lambda_reg

    def reconcile(self, S: np.ndarray,
                  y_hat: np.ndarray):
        return erm(S=S, y_hat=y_hat,
                   method=self.method, lambda_reg=self.lambda_reg)

    __call__ = reconcile