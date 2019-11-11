""" This library of supporting functions are written to perform graph partitioning according to the following reference

    References
    ----------
        .. [1] Peixoto, Tiago P. 'Entropy of stochastic blockmodel ensembles.'
               Physical Review E 85, no. 5 (2012): 056122.
        .. [2] Peixoto, Tiago P. 'Parsimonious module inference in large networks.'
               Physical review letters 110, no. 14 (2013): 148701.
        .. [3] Karrer, Brian, and Mark EJ Newman. 'Stochastic blockmodels and community structure in networks.'
               Physical Review E 83, no. 1 (2011): 016107.
"""

from typing import Tuple, Union
import timeit

import numpy as np
from scipy import sparse as sparse
use_graph_tool_options = False # for visualiziing graph partitions (optional)
if use_graph_tool_options:
    import graph_tool.all as gt

from partition import Partition, PartitionTriplet
from utils.sparse_matrix import SparseMatrix  # , SparseVector
from utils.edge_count_updates import EdgeCountUpdates


Matrix = Union[np.ndarray, SparseMatrix, sparse.lil_matrix]


def propose_new_partition(r, neighbors_out, neighbors_in, b, partition: Partition, agg_move, use_sparse):
    """Propose a new block assignment for the current node or block

        Parameters
        ----------
        r : int
                    current block assignment for the node under consideration
        neighbors_out : ndarray (int) of two columns
                    out neighbors array where the first column is the node indices and the second column is the edge weight
        neighbors_in : ndarray (int) of two columns
                    in neighbors array where the first column is the node indices and the second column is the edge weight
        b : ndarray (int)
                    array of block assignment for each node
        partition : Partition
                    the current partitioning results
        agg_move : bool
                    whether the proposal is a block move
        use_sparse : bool
                    whether the edge count matrix is stored as a sparse matrix

        Returns
        -------
        s : int
                    proposed block assignment for the node under consideration
        k_out : int
                    the out degree of the node
        k_in : int
                    the in degree of the node
        k : int
                    the total degree of the node

        Notes
        -----
        - d_u: degree of block u

        Randomly select a neighbor of the current node, and obtain its block assignment u. With probability \frac{B}{d_u + B}, randomly propose
        a block. Otherwise, randomly selects a neighbor to block u and propose its block assignment. For block (agglomerative) moves,
        avoid proposing the current block.
    """
    neighbors = np.concatenate((neighbors_out, neighbors_in))
    k_out = sum(neighbors_out[:, 1])
    k_in = sum(neighbors_in[:, 1])
    k = k_out + k_in
    if k == 0: # this node has no neighbor, simply propose a block randomly
        s = propose_random_block(r, partition.num_blocks, agg_move)
        return s, k_out, k_in, k
    rand_neighbor = np.random.choice(neighbors[:, 0], p=neighbors[:, 1] / float(k))
    u = b[rand_neighbor]
    # propose a new block randomly
    if np.random.uniform() <= partition.num_blocks/float(partition.block_degrees[u]+partition.num_blocks):  # chance inversely prop. to block_degree
        s = propose_random_block(r, partition.num_blocks, agg_move)
    else:  # propose by random draw from neighbors of block partition[rand_neighbor]
        if use_sparse:
            multinomial_prob = (partition.interblock_edge_count.getrow(u).astype(float) + partition.interblock_edge_count.getcol(u).astype(float)) / float(partition.block_degrees[u])
        else:
            multinomial_prob = (partition.interblock_edge_count[u, :].transpose() + partition.interblock_edge_count[:, u]) / float(partition.block_degrees[u])
        if agg_move:  # force proposal to be different from current block
            multinomial_prob[r] = 0
            if multinomial_prob.sum() == 0:  # the current block has no neighbors. randomly propose a different block
                candidates = set(range(partition.num_blocks))
                candidates.discard(r)
                s = np.random.choice(list(candidates))
                return s, k_out, k_in, k
            else:
                multinomial_prob = multinomial_prob / multinomial_prob.sum()
        candidates = multinomial_prob.nonzero()[0]
        s = candidates[np.flatnonzero(np.random.multinomial(1, multinomial_prob[candidates].ravel()))[0]]
    return s, k_out, k_in, k


def propose_random_block(current_block: int, num_blocks: int, agg_move: bool) -> int:
    """Proposes a random new block membership for the current node. If this is done during the block_merge step, 
    ensures that the proposed block != current block.

        Parameters
        ----------
        current_block : int
                    the current block membership
        num_blocks : int
                    the number of blocks in the current partition
        agg_move : bool
                    true if the current algorithm step is block merge (agglomerative partitioning)
        
        Returns
        -------
        proposed_block : int
                    the proposed block membership
    """
    if agg_move:  # force proposal to be different from current block
        candidates = set(range(num_blocks))
        candidates.discard(current_block)
        proposed_block = np.random.choice(list(candidates))
    else:
        proposed_block = np.random.randint(num_blocks)
    return proposed_block
# End of propose_random_block()


def compute_new_rows_cols_interblock_edge_count_matrix(M, r, s, b_out, count_out, b_in, count_in, count_self,
                                                       agg_move, use_sparse):
    """Compute the two new rows and cols of the edge count matrix under the proposal for the current node or block

        Parameters
        ----------
        M : ndarray or sparse matrix (int), shape = (#blocks, #blocks)
                    edge count matrix between all the blocks.
        r : int
                    current block assignment for the node under consideration
        s : int
                    proposed block assignment for the node under consideration
        b_out : ndarray (int)
                    blocks of the out neighbors
        count_out : ndarray (int)
                    edge counts to the out neighbor blocks
        b_in : ndarray (int)
                    blocks of the in neighbors
        count_in : ndarray (int)
                    edge counts to the in neighbor blocks
        count_self : int
                    edge counts to self
        agg_move : bool
                    whether the proposal is a block move
        use_sparse : bool
                    whether the edge count matrix is stored as a sparse matrix

        Returns
        -------
        M_r_row : ndarray or sparse matrix (int)
                    the current block row of the new edge count matrix under proposal
        M_s_row : ndarray or sparse matrix (int)
                    the proposed block row of the new edge count matrix under proposal
        M_r_col : ndarray or sparse matrix (int)
                    the current block col of the new edge count matrix under proposal
        M_s_col : ndarray or sparse matrix (int)
                    the proposed block col of the new edge count matrix under proposal

        Notes
        -----
        The updates only involve changing the entries to and from the neighboring blocks
    """
    B = M.shape[0]
    if agg_move:  # the r row and column are simply empty after this merge move
        if use_sparse:
            M_r_row = sparse.lil_matrix(M[r, :].shape, dtype=int)
            M_r_col = sparse.lil_matrix(M[:, r].shape, dtype=int)
        else:
            M_r_row = np.zeros((1, B), dtype=int)
            M_r_col = np.zeros((B, 1), dtype=int)
    else:
        if use_sparse:
            M_r_row = M[r, :].copy()
            M_r_col = M[:, r].copy()
        else:
            M_r_row = M[r, :].copy().reshape(1, B)
            M_r_col = M[:, r].copy().reshape(B, 1)
        M_r_row[0, b_out] -= count_out
        M_r_row[0, r] -= np.sum(count_in[np.where(b_in == r)])
        M_r_row[0, s] += np.sum(count_in[np.where(b_in == r)])
        M_r_col[b_in, 0] -= count_in.reshape(M_r_col[b_in, 0].shape)
        M_r_col[r, 0] -= np.sum(count_out[np.where(b_out == r)])
        M_r_col[s, 0] += np.sum(count_out[np.where(b_out == r)])
    if use_sparse:
        M_s_row = M[s, :].copy()
        M_s_col = M[:, s].copy()
    else:
        M_s_row = M[s, :].copy().reshape(1, B)
        M_s_col = M[:, s].copy().reshape(B, 1)
    M_s_row[0, b_out] += count_out
    M_s_row[0, r] -= np.sum(count_in[np.where(b_in == s)])
    M_s_row[0, s] += np.sum(count_in[np.where(b_in == s)])
    M_s_row[0, r] -= count_self
    M_s_row[0, s] += count_self
    M_s_col[b_in, 0] += count_in.reshape(M_s_col[b_in, 0].shape)
    M_s_col[r, 0] -= np.sum(count_out[np.where(b_out == s)])
    M_s_col[s, 0] += np.sum(count_out[np.where(b_out == s)])
    M_s_col[r, 0] -= count_self
    M_s_col[s, 0] += count_self

    return EdgeCountUpdates(M_r_row, M_s_row, M_r_col, M_s_col)
# End of compute_new_rows_cols_interblock_edge_count_matrix()


def block_merge_edge_count_updates(M: Matrix, r: int, s: int, b_out: np.ndarray, count_out: np.ndarray,
    b_in: np.ndarray, count_in: np.ndarray, count_self: int, use_sparse: bool) -> EdgeCountUpdates:
    """Compute the two new rows and cols of the edge count matrix under the proposal for the current block

        Parameters
        ----------
        M : ndarray or sparse matrix (int), shape = (#blocks, #blocks)
                    edge count matrix between all the blocks.
        r : int
                    current block assignment for the node under consideration
        s : int
                    proposed block assignment for the node under consideration
        b_out : ndarray (int)
                    blocks of the out neighbors
        count_out : ndarray (int)
                    edge counts to the out neighbor blocks
        b_in : ndarray (int)
                    blocks of the in neighbors
        count_in : ndarray (int)
                    edge counts to the in neighbor blocks
        count_self : int
                    edge counts to self
        use_sparse : bool
                    whether the edge count matrix is stored as a sparse matrix

        Returns
        -------
        edge_count_updates : EdgeCountUpdates
                    the rows and columns corresponding to the current and proposed block after the proposed merge

        Notes
        -----
        The updates only involve changing the entries to and from the neighboring blocks
    """
    B = M.shape[0]
    if use_sparse:
        cs = 0
        if count_self.values:
            # print("There is a self-link!")
            cs = count_self.values[0]
        M_r_row = np.zeros(B)  # DictMatrix(shape=(1, B))
        M_r_col = np.zeros(B)  # DictMatrix(shape=(B, 1))
        M_s_row = M.getrow(s)  # M[s, :].to_matrix()  # .values  # type: IndexResult
        M_s_col = M.getcol(s)  # [:, s].to_matrix()  # .values  # type: IndexResult
        M_s_row[b_out] += count_out
        M_s_row[r] -= (np.sum(count_in[np.where(b_in == s)]) + cs)
        M_s_row[s] += (np.sum(count_in[np.where(b_in == s)]) + cs)
        M_s_col[b_in] += count_in
        M_s_col[r] -= (np.sum(count_out[np.where(b_out == s)]) + cs)
        M_s_col[s] += (np.sum(count_out[np.where(b_out == s)]) + cs)
    else:
        M_r_row = np.zeros((1, B), dtype=int)
        M_r_col = np.zeros((B, 1), dtype=int)
        M_s_row = M[s, :].copy().reshape(1, B)
        M_s_col = M[:, s].copy().reshape(B, 1)
        M_s_row[0, b_out] += count_out
        M_s_row[0, r] -= np.sum(count_in[np.where(b_in == s)])
        M_s_row[0, s] += np.sum(count_in[np.where(b_in == s)])
        M_s_row[0, r] -= count_self
        M_s_row[0, s] += count_self
        M_s_col[b_in, 0] += count_in.reshape(M_s_col[b_in, 0].shape)
        M_s_col[r, 0] -= np.sum(count_out[np.where(b_out == s)])
        M_s_col[s, 0] += np.sum(count_out[np.where(b_out == s)])
        M_s_col[r, 0] -= count_self
        M_s_col[s, 0] += count_self
    return EdgeCountUpdates(M_r_row, M_s_row, M_r_col, M_s_col)
# End of block_merge_edge_count_updates()


def block_merge_edge_count_updates2(M: Matrix, r: int, s: int, b_out: np.ndarray, count_out: np.ndarray,
    b_in: np.ndarray, count_in: np.ndarray, count_self: int, use_sparse: bool) -> EdgeCountUpdates:
    """Compute the two new rows and cols of the edge count matrix under the proposal for the current block

        Parameters
        ----------
        M : ndarray or sparse matrix (int), shape = (#blocks, #blocks)
                    edge count matrix between all the blocks.
        r : int
                    current block assignment for the node under consideration
        s : int
                    proposed block assignment for the node under consideration
        b_out : ndarray (int)
                    blocks of the out neighbors
        count_out : ndarray (int)
                    edge counts to the out neighbor blocks
        b_in : ndarray (int)
                    blocks of the in neighbors
        count_in : ndarray (int)
                    edge counts to the in neighbor blocks
        count_self : int
                    edge counts to self
        use_sparse : bool
                    whether the edge count matrix is stored as a sparse matrix

        Returns
        -------
        edge_count_updates : EdgeCountUpdates
                    the rows and columns corresponding to the current and proposed block after the proposed merge

        Notes
        -----
        The updates only involve changing the entries to and from the neighboring blocks
    """
    B = M.shape[0]
    if use_sparse:
        cs = 0
        if count_self.values:
            # print("There is a self-link!")
            cs = count_self.values[0]
        M_r_row = SparseVector(np.asarray([]), np.asarray([]))  # np.zeros(B)  # DictMatrix(shape=(1, B))
        M_r_col = SparseVector(np.asarray([]), np.asarray([]))  # np.zeros(B)  # DictMatrix(shape=(B, 1))
        M_s_row = M.get_sparse_row(s)  # M[s, :].to_matrix()  # .values  # type: IndexResult
        M_s_col = M.get_sparse_col(s)  # [:, s].to_matrix()  # .values  # type: IndexResult
        M_s_row[b_out] += count_out
        M_s_row[r] -= (np.sum(count_in[np.where(b_in == s)]) + cs)
        M_s_row[s] += (np.sum(count_in[np.where(b_in == s)]) + cs)
        M_s_col[b_in] += count_in
        M_s_col[r] -= (np.sum(count_out[np.where(b_out == s)]) + cs)
        M_s_col[s] += (np.sum(count_out[np.where(b_out == s)]) + cs)
    else:
        M_r_row = np.zeros((1, B), dtype=int)
        M_r_col = np.zeros((B, 1), dtype=int)
        M_s_row = M[s, :].copy().reshape(1, B)
        M_s_col = M[:, s].copy().reshape(B, 1)
        M_s_row[0, b_out] += count_out
        M_s_row[0, r] -= np.sum(count_in[np.where(b_in == s)])
        M_s_row[0, s] += np.sum(count_in[np.where(b_in == s)])
        M_s_row[0, r] -= count_self
        M_s_row[0, s] += count_self
        M_s_col[b_in, 0] += count_in.reshape(M_s_col[b_in, 0].shape)
        M_s_col[r, 0] -= np.sum(count_out[np.where(b_out == s)])
        M_s_col[s, 0] += np.sum(count_out[np.where(b_out == s)])
        M_s_col[r, 0] -= count_self
        M_s_col[s, 0] += count_self
    return EdgeCountUpdates(M_r_row, M_s_row, M_r_col, M_s_col)
# End of block_merge_edge_count_updates()


def vertex_reassign_edge_count_updates(M: Matrix, r: int, s: int, b_out: np.ndarray, count_out: np.ndarray,
    b_in: np.ndarray, count_in: np.ndarray, count_self: int, use_sparse: bool):
    """Compute the two new rows and cols of the edge count matrix under the proposal for the current vertex.

        Parameters
        ----------
        M : ndarray or sparse matrix (int), shape = (#blocks, #blocks)
                    edge count matrix between all the blocks.
        r : int
                    current block assignment for the node under consideration
        s : int
                    proposed block assignment for the node under consideration
        b_out : ndarray (int)
                    blocks of the out neighbors
        count_out : ndarray (int)
                    edge counts to the out neighbor blocks
        b_in : ndarray (int)
                    blocks of the in neighbors
        count_in : ndarray (int)
                    edge counts to the in neighbor blocks
        count_self : int
                    edge counts to self
        use_sparse : bool
                    whether the edge count matrix is stored as a sparse matrix

        Returns
        -------
        edge_count_updates : EdgeCountUpdates
                    the rows and columns corresponding to the current and proposed block after the proposed merge

        Notes
        -----
        The updates only involve changing the entries to and from the neighboring blocks
    """
    B = M.shape[0]
    if use_sparse:
        M_r_row = M.getrow(r)  # M[r, :].copy()
        M_r_col = M.getcol(r)  # [:, r].copy()
        M_s_row = M.getrow(s)  # [s, :].copy()
        M_s_col = M.getcol(s)  # [:, s].copy()    

        M_r_row[b_out] -= count_out
        count_in_r = np.sum(count_in[np.where(b_in == r)])
        M_r_row[r] -= count_in_r
        M_r_row[s] += count_in_r
        M_r_col[b_in] -= count_in  # .reshape(M_r_col[b_in, 0].shape)
        count_out_r = np.sum(count_out[np.where(b_out == r)])
        M_r_col[r] -= count_out_r
        M_r_col[s] += count_out_r

        M_s_row[b_out] += count_out
        count_in_s = np.sum(count_in[np.where(b_in == s)])
        M_s_row[r] -= (count_in_s + count_self)
        M_s_row[s] += (count_in_s + count_self)
        M_s_col[b_in] += count_in  # .reshape(M_s_col[b_in, 0].shape)
        count_out_s = np.sum(count_out[np.where(b_out == s)])
        M_s_col[r] -= (count_out_s + count_self)
        M_s_col[s] += (count_out_s + count_self)
    else:
        M_r_row = M[r, :].copy().reshape(1, B)
        M_r_col = M[:, r].copy().reshape(B, 1)
        M_s_row = M[s, :].copy().reshape(1, B)
        M_s_col = M[:, s].copy().reshape(B, 1)
        M_r_row[0, b_out] -= count_out
        M_r_row[0, r] -= np.sum(count_in[np.where(b_in == r)])
        M_r_row[0, s] += np.sum(count_in[np.where(b_in == r)])
        M_r_col[b_in, 0] -= count_in.reshape(M_r_col[b_in, 0].shape)
        M_r_col[r, 0] -= np.sum(count_out[np.where(b_out == r)])
        M_r_col[s, 0] += np.sum(count_out[np.where(b_out == r)])

        M_s_row[0, b_out] += count_out
        M_s_row[0, r] -= np.sum(count_in[np.where(b_in == s)])
        M_s_row[0, s] += np.sum(count_in[np.where(b_in == s)])
        M_s_row[0, r] -= count_self
        M_s_row[0, s] += count_self
        M_s_col[b_in, 0] += count_in.reshape(M_s_col[b_in, 0].shape)
        M_s_col[r, 0] -= np.sum(count_out[np.where(b_out == s)])
        M_s_col[s, 0] += np.sum(count_out[np.where(b_out == s)])
        M_s_col[r, 0] -= count_self
        M_s_col[s, 0] += count_self

    return EdgeCountUpdates(M_r_row, M_s_row, M_r_col, M_s_col)
# End of compute_new_rows_cols_interblock_edge_count_matrix()


def compute_new_block_degrees(r, s, partition: Partition, k_out, k_in, k):
    """Compute the new block degrees under the proposal for the current node or block

        Parameters
        ----------
        r : int
                    current block assignment for the node under consideration
        s : int
                    proposed block assignment for the node under consideration
        d_out : ndarray (int)
                    the current out degree of each block
        d_in : ndarray (int)
                    the current in degree of each block
        d : ndarray (int)
                    the current total degree of each block
        k_out : int
                    the out degree of the node
        k_in : int
                    the in degree of the node
        k : int
                    the total degree of the node

        Returns
        -------
        d_out_new : ndarray (int)
                    the new out degree of each block under proposal
        d_in_new : ndarray (int)
                    the new in degree of each block under proposal
        d_new : ndarray (int)
                    the new total degree of each block under proposal

        Notes
        -----
        The updates only involve changing the degrees of the current and proposed block
    """
    new = []
    for old, degree in zip([partition.block_degrees_out, partition.block_degrees_in, partition.block_degrees], [k_out, k_in, k]):
        new_d = old.copy()
        new_d[r] -= degree
        new_d[s] += degree
        new.append(new_d)
    return new


def compute_Hastings_correction(b_out, count_out, b_in, count_in, s, partition: Partition, M_r_row, M_r_col, d_new,
    use_sparse: bool) -> float:
    """Compute the Hastings correction for the proposed block from the current block

        Parameters
        ----------
        b_out : ndarray (int)
                    blocks of the out neighbors
        count_out : ndarray (int)
                    edge counts to the out neighbor blocks
        b_in : ndarray (int)
                    blocks of the in neighbors
        count_in : ndarray (int)
                    edge counts to the in neighbor blocks
        s : int
                    proposed block assignment for the node under consideration
        partition : Partition
                    the current partitioning results
        M_r_row : ndarray or sparse matrix (int)
                    the current block row of the new edge count matrix under proposal
        M_r_col : ndarray or sparse matrix (int)
                    the current block col of the new edge count matrix under proposal
        d_new : ndarray (int)
                    new block degrees under the proposal
        use_sparse : bool
                    whether the edge count matrix is stored as a sparse matrix

        Returns
        -------
        Hastings_correction : float
                    term that corrects for the transition asymmetry between the current block and the proposed block

        Notes
        -----
        - p_{i, s \rightarrow r} : for node i, probability of proposing block r if its current block is s
        - p_{i, r \rightarrow s} : for node i, probability of proposing block s if its current block is r
        - r : current block for node i
        - s : proposed block for node i
        - M^-: current edge count matrix between the blocks
        - M^+: new edge count matrix under the proposal
        - d^-_t: current degree of block t
        - d^+_t: new degree of block t under the proposal
        - \mathbf{b}_{\mathcal{N}_i}: the neighboring blocks to node i
        - k_i: the degree of node i
        - k_{i,t} : the degree of node i to block t (i.e. number of edges to and from block t)
        - B : the number of blocks

        The Hastings correction is:

        \frac{p_{i, s \rightarrow r}}{p_{i, r \rightarrow s}}

        where

        p_{i, r \rightarrow s} = \sum_{t \in \{\mathbf{b}_{\mathcal{N}_i}^-\}} \left[ {\frac{k_{i,t}}{k_i} \frac{M_{ts}^- + M_{st}^- + 1}{d^-_t+B}}\right]

        p_{i, s \rightarrow r} = \sum_{t \in \{\mathbf{b}_{\mathcal{N}_i}^-\}} \left[ {\frac{k_{i,t}}{k_i} \frac{M_{tr}^+ + M_{rt}^+ +1}{d_t^++B}}\right]

        summed over all the neighboring blocks t
    """
    t, idx = np.unique(np.append(b_out, b_in), return_inverse=True)  # find all the neighboring blocks
    count = np.bincount(idx, weights=np.append(count_out, count_in)).astype(int)  # count edges to neighboring blocks
    if use_sparse:
        M_t_s = partition.interblock_edge_count.getcol(s)[t]
        M_s_t = partition.interblock_edge_count.getrow(s)[t]
        M_r_row = M_r_row[t]
        M_r_col = M_r_col[t]
    else:
        M_t_s = partition.interblock_edge_count[t, s].ravel()
        M_s_t = partition.interblock_edge_count[s, t].ravel()
        M_r_row = M_r_row[0, t].ravel()
        M_r_col = M_r_col[t, 0].ravel()
        
    p_forward = np.sum(count*(M_t_s + M_s_t + 1) / (partition.block_degrees[t] + float(partition.num_blocks)))
    p_backward = np.sum(count*(M_r_row + M_r_col + 1) / (d_new[t] + float(partition.num_blocks)))
    return p_backward / p_forward
# End of compute_Hastings_correction()


def compute_delta_entropy(r, s, partition: Partition, edge_count_updates: EdgeCountUpdates, d_out_new, d_in_new,
    use_sparse) -> float:
    """Compute change in entropy under the proposal. Reduced entropy means the proposed block is better than the 
    current block.

        Parameters
        ----------
        r : int
                    current block assignment for the node under consideration
        s : int
                    proposed block assignment for the node under consideration
        partition : Partition
                    the current partitioning results
        edge_count_updates : EdgeCountUpdates
                    the updates to the current partition's edge count
        d_out_new : ndarray (int)
                    the new out degree of each block under proposal
        d_in_new : ndarray (int)
                    the new in degree of each block under proposal
        use_sparse : bool
                    whether the edge count matrix is stored as a sparse matrix

        Returns
        -------
        delta_entropy : float
                    entropy under the proposal minus the current entropy

        Notes
        -----
        - M^-: current edge count matrix between the blocks
        - M^+: new edge count matrix under the proposal
        - d^-_{t, in}: current in degree of block t
        - d^-_{t, out}: current out degree of block t
        - d^+_{t, in}: new in degree of block t under the proposal
        - d^+_{t, out}: new out degree of block t under the proposal
        
        The difference in entropy is computed as:
        
        \dot{S} = \sum_{t_1, t_2} {\left[ -M_{t_1 t_2}^+ \text{ln}\left(\frac{M_{t_1 t_2}^+}{d_{t_1, out}^+ d_{t_2, in}^+}\right) + M_{t_1 t_2}^- \text{ln}\left(\frac{M_{t_1 t_2}^-}{d_{t_1, out}^- d_{t_2, in}^-}\right)\right]}
        
        where the sum runs over all entries $(t_1, t_2)$ in rows and cols $r$ and $s$ of the edge count matrix
    """
    if use_sparse: # computation in the sparse matrix is slow so convert to numpy arrays since operations are on only two rows and cols
        return compute_delta_entropy_sparse(r, s, partition, edge_count_updates, d_out_new, d_in_new)

    M_r_row = edge_count_updates.block_row
    M_s_row = edge_count_updates.proposal_row
    M_r_col = edge_count_updates.block_col
    M_s_col = edge_count_updates.proposal_col
    M_r_t1 = partition.interblock_edge_count[r, :]
    M_s_t1 = partition.interblock_edge_count[s, :]
    M_t2_r = partition.interblock_edge_count[:, r]
    M_t2_s = partition.interblock_edge_count[:, s]

    # remove r and s from the cols to avoid double counting
    idx = list(range(len(d_in_new)))
    del idx[max(r, s)]
    del idx[min(r, s)]
    M_r_col = M_r_col[idx]
    M_s_col = M_s_col[idx]
    M_t2_r = M_t2_r[idx]
    M_t2_s = M_t2_s[idx]
    d_out_new_ = d_out_new[idx]
    d_out_ = partition.block_degrees_out[idx]

    # only keep non-zero entries to avoid unnecessary computation
    d_in_new_r_row = d_in_new[M_r_row.ravel().nonzero()]
    d_in_new_s_row = d_in_new[M_s_row.ravel().nonzero()]
    M_r_row = M_r_row[M_r_row.nonzero()]
    M_s_row = M_s_row[M_s_row.nonzero()]
    d_out_new_r_col = d_out_new_[M_r_col.ravel().nonzero()]
    d_out_new_s_col = d_out_new_[M_s_col.ravel().nonzero()]
    M_r_col = M_r_col[M_r_col.nonzero()]
    M_s_col = M_s_col[M_s_col.nonzero()]
    d_in_r_t1 = partition.block_degrees_in[M_r_t1.ravel().nonzero()]
    d_in_s_t1 = partition.block_degrees_in[M_s_t1.ravel().nonzero()]
    M_r_t1= M_r_t1[M_r_t1.nonzero()]
    M_s_t1 = M_s_t1[M_s_t1.nonzero()]
    d_out_r_col = d_out_[M_t2_r.ravel().nonzero()]
    d_out_s_col = d_out_[M_t2_s.ravel().nonzero()]
    M_t2_r = M_t2_r[M_t2_r.nonzero()]
    M_t2_s = M_t2_s[M_t2_s.nonzero()]

    # sum over the two changed rows and cols
    delta_entropy = 0
    delta_entropy -= np.sum(M_r_row * np.log(M_r_row.astype(float) / d_in_new_r_row / d_out_new[r]))
    delta_entropy -= np.sum(M_s_row * np.log(M_s_row.astype(float) / d_in_new_s_row / d_out_new[s]))
    delta_entropy -= np.sum(M_r_col * np.log(M_r_col.astype(float) / d_out_new_r_col / d_in_new[r]))
    delta_entropy -= np.sum(M_s_col * np.log(M_s_col.astype(float) / d_out_new_s_col / d_in_new[s]))
    delta_entropy += np.sum(M_r_t1 * np.log(M_r_t1.astype(float) / d_in_r_t1 / partition.block_degrees_out[r]))
    delta_entropy += np.sum(M_s_t1 * np.log(M_s_t1.astype(float) / d_in_s_t1 / partition.block_degrees_out[s]))
    delta_entropy += np.sum(M_t2_r * np.log(M_t2_r.astype(float) / d_out_r_col / partition.block_degrees_in[r]))
    delta_entropy += np.sum(M_t2_s * np.log(M_t2_s.astype(float) / d_out_s_col / partition.block_degrees_in[s]))
    return delta_entropy
# End of compute_delta_entropy()


def compute_delta_entropy_sparse(r, s, partition: Partition, edge_count_updates: EdgeCountUpdates, d_out_new,
    d_in_new) -> float:
    """Compute change in entropy under the proposal. Reduced entropy means the proposed block is better than the current block.

        Parameters
        ----------
        r : int
                    current block assignment for the node under consideration
        s : int
                    proposed block assignment for the node under consideration
        partition : Partition
                    the current partitioning results
        edge_count_updates : EdgeCountUpdates
                    the updates to the current partition's edge count
        d_out_new : ndarray (int)
                    the new out degree of each block under proposal
        d_in_new : ndarray (int)
                    the new in degree of each block under proposal

        Returns
        -------
        delta_entropy : float
                    entropy under the proposal minus the current entropy

        Notes
        -----
        - M^-: current edge count matrix between the blocks
        - M^+: new edge count matrix under the proposal
        - d^-_{t, in}: current in degree of block t
        - d^-_{t, out}: current out degree of block t
        - d^+_{t, in}: new in degree of block t under the proposal
        - d^+_{t, out}: new out degree of block t under the proposal
        
        The difference in entropy is computed as:
        
        \dot{S} = \sum_{t_1, t_2} {\left[ -M_{t_1 t_2}^+ \text{ln}\left(\frac{M_{t_1 t_2}^+}{d_{t_1, out}^+ d_{t_2, in}^+}\right) + M_{t_1 t_2}^- \text{ln}\left(\frac{M_{t_1 t_2}^-}{d_{t_1, out}^- d_{t_2, in}^-}\right)\right]}
        
        where the sum runs over all entries $(t_1, t_2)$ in rows and cols $r$ and $s$ of the edge count matrix
    """
    M_r_row = edge_count_updates.block_row  # .getrow(0)
    M_s_row = edge_count_updates.proposal_row  # .getrow(0)
    M_r_col = edge_count_updates.block_col  # .getcol(0)
    M_s_col = edge_count_updates.proposal_col  # .getcol(0)
    M_r_t1 = partition.interblock_edge_count.getrow(r)
    M_s_t1 = partition.interblock_edge_count.getrow(s)
    M_t2_r = partition.interblock_edge_count.getcol(r)
    M_t2_s = partition.interblock_edge_count.getcol(s)

    idx = list(range(len(d_in_new)))
    del idx[max(r, s)]
    del idx[min(r, s)]
    M_r_col = M_r_col[idx]
    M_s_col = M_s_col[idx]
    M_t2_r = M_t2_r[idx]
    M_t2_s = M_t2_s[idx]
    d_out_new_ = d_out_new[idx]
    d_out_ = partition.block_degrees_out[idx]

    # only keep non-zero entries to avoid unnecessary computation
    d_in_new_r_row = d_in_new[M_r_row.ravel().nonzero()]
    d_in_new_s_row = d_in_new[M_s_row.ravel().nonzero()]
    M_r_row = M_r_row[M_r_row.nonzero()]
    M_s_row = M_s_row[M_s_row.nonzero()]
    d_out_new_r_col = d_out_new_[M_r_col.ravel().nonzero()]
    d_out_new_s_col = d_out_new_[M_s_col.ravel().nonzero()]
    M_r_col = M_r_col[M_r_col.nonzero()]
    M_s_col = M_s_col[M_s_col.nonzero()]
    d_in_r_t1 = partition.block_degrees_in[M_r_t1.ravel().nonzero()]
    d_in_s_t1 = partition.block_degrees_in[M_s_t1.ravel().nonzero()]
    M_r_t1= M_r_t1[M_r_t1.nonzero()]
    M_s_t1 = M_s_t1[M_s_t1.nonzero()]
    d_out_r_col = d_out_[M_t2_r.ravel().nonzero()]
    d_out_s_col = d_out_[M_t2_s.ravel().nonzero()]
    M_t2_r = M_t2_r[M_t2_r.nonzero()]
    M_t2_s = M_t2_s[M_t2_s.nonzero()]

    # sum over the two changed rows and cols
    delta_entropy = 0
    delta_entropy -= np.sum(M_r_row * np.log(M_r_row.astype(float) / d_in_new_r_row / d_out_new[r]))
    delta_entropy -= np.sum(M_s_row * np.log(M_s_row.astype(float) / d_in_new_s_row / d_out_new[s]))
    delta_entropy -= np.sum(M_r_col * np.log(M_r_col.astype(float) / d_out_new_r_col / d_in_new[r]))
    delta_entropy -= np.sum(M_s_col * np.log(M_s_col.astype(float) / d_out_new_s_col / d_in_new[s]))
    delta_entropy += np.sum(M_r_t1 * np.log(M_r_t1.astype(float) / d_in_r_t1 / partition.block_degrees_out[r]))
    delta_entropy += np.sum(M_s_t1 * np.log(M_s_t1.astype(float) / d_in_s_t1 / partition.block_degrees_out[s]))
    delta_entropy += np.sum(M_t2_r * np.log(M_t2_r.astype(float) / d_out_r_col / partition.block_degrees_in[r]))
    delta_entropy += np.sum(M_t2_s * np.log(M_t2_s.astype(float) / d_out_s_col / partition.block_degrees_in[s]))
    return delta_entropy
# End of compute_delta_entropy_sparse()


def carry_out_best_merges(delta_entropy_for_each_block, best_merge_for_each_block, partition: Partition) -> Partition:
    """Execute the best merge (agglomerative) moves to reduce a set number of blocks

        Parameters
        ----------
        delta_entropy_for_each_block : ndarray (float)
                    the delta entropy for merging each block
        best_merge_for_each_block : ndarray (int)
                    the best block to merge with for each block
        partition : Partition
                    the current partitioning results

        Returns
        -------
        partition : Partition
                    the modified partition, with the merges carried out
    """
    bestMerges = delta_entropy_for_each_block.argsort()
    block_map = np.arange(partition.num_blocks)
    num_merge = 0
    counter = 0
    while num_merge < partition.num_blocks_to_merge:
        mergeFrom = bestMerges[counter]
        mergeTo = block_map[best_merge_for_each_block[bestMerges[counter]]]
        counter += 1
        if mergeTo != mergeFrom:
            block_map[np.where(block_map == mergeFrom)] = mergeTo
            partition.block_assignment[np.where(partition.block_assignment == mergeFrom)] = mergeTo
            num_merge += 1
    remaining_blocks = np.unique(partition.block_assignment)
    mapping = -np.ones(partition.num_blocks, dtype=int)
    mapping[remaining_blocks] = np.arange(len(remaining_blocks))
    partition.block_assignment = mapping[partition.block_assignment]
    partition.num_blocks -= partition.num_blocks_to_merge
    return partition
# End of carry_out_best_merges()


def update_partition(partition: Partition, ni: int, r: int, s: int, edge_count_updates: EdgeCountUpdates,
    d_out_new: np.ndarray, d_in_new: np.ndarray, d_new: np.ndarray, use_sparse: bool) -> Partition:
    """Move the current node to the proposed block and update the edge counts

        Parameters
        ----------
        partition : Partition
                    the current partitioning results
        ni : int
                    current node index
        r : int
                    current block assignment for the node under consideration
        s : int
                    proposed block assignment for the node under consideration
        edge_count_updates : EdgeCountUpdates
                    the current and proposed rows and columns of the interblock edge count updates under the proposal 
        d_out_new : ndarray (int)
                    the new out degree of each block under proposal
        d_in_new : ndarray (int)
                    the new in degree of each block under proposal
        d_new : ndarray (int)
                    the new total degree of each block under proposal
        use_sparse : bool
                    whether the edge count matrix is stored as a sparse matrix

        Returns
        -------
        partition : Partition
                    the updated partitioning results
    """
    partition.block_assignment[ni] = s
    if use_sparse:
        partition.interblock_edge_count.update_edge_counts(r, s, edge_count_updates)
    else:
        partition.interblock_edge_count[r, :] = edge_count_updates.block_row
        partition.interblock_edge_count[s, :] = edge_count_updates.proposal_row
        partition.interblock_edge_count[:, r] = edge_count_updates.block_col.reshape(partition.interblock_edge_count[:, r].shape)
        partition.interblock_edge_count[:, s] = edge_count_updates.proposal_col.reshape(partition.interblock_edge_count[:, s].shape)
    partition.block_degrees_out = d_out_new
    partition.block_degrees_in = d_in_new
    partition.block_degrees = d_new
    return partition
# End of update_partition()


def compute_overall_entropy(partition: Partition, N, E, use_sparse) -> float:
    """Compute the overall entropy, including the model entropy as well as the data entropy, on the current partition.
       The best partition with an optimal number of blocks will minimize this entropy.

        Parameters
        ----------
        partition : Partition
                    the current partitioning results
        N : int
                    number of nodes in the graph
        E : int
                    number of edges in the graph
        use_sparse : bool
                    whether the edge count matrix is stored as a sparse matrix

        Returns
        -------
        S : float
                    the overall entropy of the current partition

        Notes
        -----
        - M: current edge count matrix
        - d_{t, out}: current out degree of block t
        - d_{t, in}: current in degree of block t
        - B: number of blocks
        - C: some constant invariant to the partition
        
        The overall entropy of the partition is computed as:
        
        S = E\;h\left(\frac{B^2}{E}\right) + N \ln(B) - \sum_{t_1, t_2} {M_{t_1 t_2} \ln\left(\frac{M_{t_1 t_2}}{d_{t_1, out} d_{t_2, in}}\right)} + C
        
        where the function h(x)=(1+x)\ln(1+x) - x\ln(x) and the sum runs over all entries (t_1, t_2) in the edge count matrix
    """
    nonzeros = partition.interblock_edge_count.nonzero()  # all non-zero entries
    if use_sparse:
        edge_count_entries = partition.interblock_edge_count.values()
    else:
        edge_count_entries = partition.interblock_edge_count[nonzeros[0], nonzeros[1]]

    entries = edge_count_entries * np.log(edge_count_entries / (partition.block_degrees_out[nonzeros[0]] * partition.block_degrees_in[nonzeros[1]]).astype(float))
    data_S = -np.sum(entries)
    model_S_term = partition.num_blocks**2 / float(E)
    model_S = E * (1 + model_S_term) * np.log(1 + model_S_term) - model_S_term * np.log(model_S_term) + N*np.log(partition.num_blocks)
    S = model_S + data_S
    return S


def prepare_for_partition_on_next_num_blocks(partition: Partition, partition_triplet: PartitionTriplet,
    B_rate: float) -> Tuple[Partition, PartitionTriplet]:
    """Checks to see whether the current partition has the optimal number of blocks. If not, the next number of blocks
       to try is determined and the intermediate variables prepared.

        Parameters
        ----------
        partition : Partition
                the most recent partitioning results
        partition_triplet : Partition
                the triplet of the three best partitioning results for Fibonacci search
        B_rate : float
                    the ratio on the number of blocks to reduce before the golden ratio bracket is established

        Returns:
        ----------
        partition : Partition
                the partitioning results to use for the next iteration of the algorithm
        partition_triplet : PartitionTriplet
                the updated triplet of the three best partitioning results for Fibonacci search

        Notes
        -----
        The holders for the best three partitions so far and their statistics will be stored in the order of the number
        of blocks, starting from the highest to the lowest. The middle entry is always the best so far. The number of
        blocks is reduced by a fixed rate until the golden ratio bracket (three best partitions with the middle one
        being the best) is established. Once the golden ratio bracket is established, perform golden ratio search until
        the bracket is narrowed to consecutive number of blocks where the middle one is identified as the optimal
        number of blocks.
    """
    optimal_B_found = False
    partition.num_blocks_to_merge = 0

    partition_triplet.update(partition)
    if partition_triplet.partitions[2] is None:  # Golden Ratio bracket not yet established
        partition = partition_triplet.partitions[1].copy()
        partition.num_blocks_to_merge = int(partition.num_blocks * B_rate)
        if (partition.num_blocks_to_merge == 0):  # not enough number of blocks to merge, so done
            optimal_B_found = True
    else:  # golden ratio search bracket established
        # If we have found the partition with the optimal number of blocks
        if (partition_triplet.partitions[0] is not None and
            partition_triplet.partitions[0].num_blocks - partition_triplet.partitions[2].num_blocks == 2):
            partition = partition_triplet.partitions[1].copy()
            optimal_B_found = True
        elif (partition_triplet.partitions[0] is None and
              partition_triplet.partitions[1].num_blocks - partition_triplet.partitions[2].num_blocks == 1):
            partition = partition_triplet.partitions[1].copy()
            optimal_B_found = True
        else:  # not done yet, find the next number of block to try according to the golden ratio search
            # If partition_triplet looks like [0, Partition with B blocks, Partition with B - X blocks]
            if (partition_triplet.partitions[0] is None and
                partition_triplet.partitions[1].num_blocks > partition_triplet.partitions[2].num_blocks):
                index = 1
            # Else iff the higher segment in bracket is bigger
            elif ((partition_triplet.partitions[0].num_blocks - partition_triplet.partitions[1].num_blocks) >= 
                (partition_triplet.partitions[1].num_blocks - partition_triplet.partitions[2].num_blocks)):
                index = 0
            else:  # the lower segment in the bracket is bigger
                index = 1
            next_B_to_try = partition_triplet.partitions[index + 1].num_blocks
            next_B_to_try += np.round((
                partition_triplet.partitions[index].num_blocks - partition_triplet.partitions[index + 1].num_blocks
            ) * 0.618).astype(int)
            partition = partition_triplet.partitions[index].copy()
            partition.num_blocks_to_merge = partition_triplet.partitions[index].num_blocks - next_B_to_try

    partition_triplet.optimal_num_blocks_found = optimal_B_found
    return partition, partition_triplet
# End of prepare_for_partition_on_next_num_blocks()


def plot_graph_with_partition(out_neighbors, b, graph_object=None, pos=None):
    """Plot the graph with force directed layout and color/shape each node according to its block assignment

        Parameters
        ----------
        out_neighbors : list of ndarray; list length is N, the number of nodes
                    each element of the list is a ndarray of out neighbors, where the first column is the node indices
                    and the second column the corresponding edge weights
        b : ndarray (int)
                    array of block assignment for each node
        graph_object : graph tool object, optional
                    if a graph object already exists, use it to plot the graph
        pos : ndarray (float) shape = (#nodes, 2), optional
                    if node positions are given, plot the graph using them

        Returns
        -------
        graph_object : graph tool object
                    the graph tool object containing the graph and the node position info"""

    if len(out_neighbors) <= 5000:
        if graph_object is None:
            graph_object = gt.Graph()
            edge_list = [(i, j) for i in range(len(out_neighbors)) if len(out_neighbors[i]) > 0 for j in
                         out_neighbors[i][:, 0]]
            graph_object.add_edge_list(edge_list)
            if pos is None:
                graph_object.vp['pos'] = gt.sfdp_layout(graph_object)
            else:
                graph_object.vp['pos'] = graph_object.new_vertex_property("vector<float>")
                for v in graph_object.vertices():
                    graph_object.vp['pos'][v] = pos[graph_object.vertex_index[v], :]
        block_membership = graph_object.new_vertex_property("int")
        vertex_shape = graph_object.new_vertex_property("int")
        block_membership.a = b[0:len(out_neighbors)]
        vertex_shape.a = np.mod(block_membership.a, 10)
        gt.graph_draw(graph_object, inline=True, output_size=(400, 400), pos=graph_object.vp['pos'],
                      vertex_shape=vertex_shape,
                      vertex_fill_color=block_membership, edge_pen_width=0.1, edge_marker_size=1, vertex_size=7)
    else:
        print('That\'s a big graph!')
    return graph_object
