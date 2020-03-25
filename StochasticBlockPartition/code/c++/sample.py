"""Helper functions for performing different kinds of sampling.
"""

import argparse
from typing import List
from copy import copy

from graph_tool import Graph
import numpy as np

from samplestate import SampleState
from samplestate import UniformRandomSampleState
from samplestate import RandomWalkSampleState
from samplestate import RandomJumpSampleState
from samplestate import DegreeWeightedSampleState
from samplestate import RandomNodeNeighborSampleState
from samplestate import ForestFireSampleState
from samplestate import ExpansionSnowballSampleState


class Sample():
    """Stores the variables needed to create a subgraph.
    """

    def __init__(self, state: SampleState, graph: Graph, old_true_block_assignment: np.ndarray) -> None:
        """Creates a new Sample object. Contains information about the sampled vertices and edges, the mapping of
        sampled vertices to the original graph vertices, and the true block membership for the sampled vertices.

        Parameters
        ----------
        state : SampleState
            contains the sampled vertices
        graph : Graph
            the graph from which the sample is taken
        old_true_block_assignment : np.ndarray[int]
            the vertex-to-community assignment array. Currently assumes that community assignment is non-overlapping.
        """
        self.state = state
        sampled_vertices = state.sample_idx[-state.sample_size:]
        self.vertex_mapping = dict([(v, k) for k, v in enumerate(sampled_vertices)])
        self.out_neighbors = list()  # type: List[np.ndarray]
        self.in_neighbors = list()  # type: List[np.ndarray]
        self.num_edges = 0
        for index in sampled_vertices:
            # get_out_neighbors actually returns just a list of neighbors. If we need the edge weights later, we will
            # need to use get_out_edges, which returns an array with structure [[from, to, weight], ...]
            out_neighbors = graph.get_out_neighbors(index)
            out_mask = np.isin(out_neighbors, sampled_vertices, assume_unique=False)
            sampled_out_neighbors = out_neighbors[out_mask]
            for i in range(len(sampled_out_neighbors)):
                sampled_out_neighbors[i] = self.vertex_mapping[sampled_out_neighbors[i]]
            self.out_neighbors.append(sampled_out_neighbors)
            in_neighbors = graph.get_in_neighbors(index)
            in_mask = np.isin(in_neighbors, sampled_vertices, assume_unique=False)
            sampled_in_neighbors = in_neighbors[in_mask]
            for i in range(len(sampled_in_neighbors)):
                sampled_in_neighbors[i] = self.vertex_mapping[sampled_in_neighbors[i]]
            self.in_neighbors.append(sampled_in_neighbors)
            self.num_edges += np.sum(out_mask) + np.sum(in_mask)
        true_block_assignment = old_true_block_assignment[sampled_vertices]
        # Assuming the sample doesn't capture all the blocks, the block numbers in the sample may not be consecutive
        # The true_blocks_mapping ensures that they are consecutive
        true_blocks = list(set(true_block_assignment))
        self.true_blocks_mapping = dict([(v, k) for k, v in enumerate(true_blocks)])
        self.true_block_assignment = np.asarray([self.true_blocks_mapping[b] for b in true_block_assignment])
        self.sample_num = len(self.vertex_mapping)
    # End of __init__()

    @staticmethod
    def create_sample(graph: Graph, old_true_block_assignment: np.ndarray, args: argparse.Namespace,
                      prev_state: SampleState) -> 'Sample':
        """Performs sampling according to the sample type in args.

        TODO: either re-write how this method is used, or get rid of it - it seems to be a code smell.
        """
        # prev_state = SampleState.create_sample_state(graph.num_vertices(), prev_state, args)
        if args.sample_type == "uniform_random":
            return Sample.uniform_random_sample(graph, old_true_block_assignment, prev_state, args)
        elif args.sample_type == "random_walk":
            return Sample.random_walk_sample(graph, old_true_block_assignment, prev_state, args)
        elif args.sample_type == "random_jump":
            return Sample.random_jump_sample(graph, old_true_block_assignment, prev_state, args)
        elif args.sample_type == "degree_weighted":
            return Sample.degree_weighted_sample(graph, old_true_block_assignment, prev_state, args)
        elif args.sample_type == "random_node_neighbor":
            return Sample.random_node_neighbor_sample(graph, old_true_block_assignment, prev_state, args)
        elif args.sample_type == "forest_fire":
            return Sample.forest_fire_sample(graph, old_true_block_assignment, prev_state, args)
        elif args.sample_type == "expansion_snowball":
            return Sample.expansion_snowball_sample(graph, old_true_block_assignment, prev_state, args)
        else:
            raise NotImplementedError("Sample type: {} is not implemented!".format(args.sample_type))
    # End of create_sample()

    @staticmethod
    def uniform_random_sample(graph: Graph, assignment: np.ndarray, prev_state: UniformRandomSampleState,
                              args: argparse.Namespace) -> 'Sample':
        """Uniform random sampling. All vertices are selected with the same probability.

        Parameters
        ----------
        graph : Graph
            the graph from which to sample vertices
        assignment : np.ndarray[int]
            the vertex-to-community assignment
        prev_state : UniformRandomSampleState
            the state of the previous sample in the stack. If there is no previous sample, an empty SampleState object
            should be passed in here.
        args : argparse.Namespace
            the command-line arguments provided by the user

        Returns
        -------
        sample : Sample
            the resulting Sample object
        """
        state = UniformRandomSampleState(graph.num_vertices(), prev_state)
        sample_num = int((graph.num_vertices() * (args.sample_size / 100)) / args.sample_iterations)
        choices = np.setdiff1d(np.asarray(range(graph.num_vertices())), state.sample_idx)
        state.sample_idx = np.concatenate(
            (state.sample_idx, np.random.choice(choices, sample_num, replace=False)),
            axis=None
        )
        return Sample(state, graph, assignment)
    # End of uniform_random_sampling()

    @staticmethod
    def random_walk_sample(graph: Graph, old_true_block_assignment: np.ndarray, prev_state: RandomWalkSampleState,
                           args: argparse.Namespace) -> 'Sample':
        """Random walk sampling. Start from a vertex and walk along the edges, sampling every vertex that is a part of
        the walk. With a probability of 0.15, restart the walk from the original vertex. To prevent getting stuck,
        after making N attempts, where N = the target number of vertices in the sample, change the starting vertex to a
        random vertex.

        Parameters
        ----------
        graph : Graph
            the graph from which to sample vertices
        assignment : np.ndarray[int]
            the vertex-to-community assignment
        prev_state : RandomWalkSampleState
            the state of the previous sample in the stack. If there is no previous sample, an empty SampleState object
            should be passed in here.
        args : argparse.Namespace
            the command-line arguments provided by the user

        Returns
        -------
        sample : Sample
            the resulting Sample object
        """
        state = RandomWalkSampleState(graph.num_vertices(), prev_state)
        sample_num = int((graph.num_vertices() * (args.sample_size / 100)) / args.sample_iterations)
        sample_num += len(state.sample_idx)
        num_tries = 0
        start = np.random.randint(sample_num)  # start with a random vertex
        vertex = start

        while len(state.index_set) == 0 or len(state.index_set) % sample_num != 0:
            num_tries += 1
            if not state.sampled_marker[vertex]:
                state.index_set.append(vertex)
                state.sampled_marker[vertex] = True
            if num_tries % sample_num == 0:  # If the number of tries is large, restart from new random vertex
                start = np.random.randint(sample_num)
                vertex = start
                num_tries = 0
            elif np.random.random() < 0.15:  # With a probability of 0.15, restart at original node
                vertex = start
            elif len(graph.get_out_neighbors(vertex)) > 0:  # If the vertex has out neighbors, go to one of them
                vertex = np.random.choice(graph.get_out_neighbors(vertex))
            else:  # Otherwise, restart from the original vertex
                if len(graph.get_out_neighbors(start)) == 0:  # if original vertex has no out neighbors, change it
                    start = np.random.randint(sample_num)
                vertex = start

        state.sample_idx = np.asarray(state.index_set)
        return Sample(state, graph, old_true_block_assignment)
    # End of Random_walk_sampling()

    @staticmethod
    def random_jump_sample(graph: Graph, old_true_block_assignment: np.ndarray, prev_state: RandomJumpSampleState,
                           args: argparse.Namespace) -> 'Sample':
        """Random jump sampling. Start from a vertex and walk along the edges, sampling every vertex that is a part of
        the walk. With a probability of 0.15, restart the walk from a new vertex.

        Parameters
        ----------
        graph : Graph
            the graph from which to sample vertices
        assignment : np.ndarray[int]
            the vertex-to-community assignment
        prev_state : RandomWalkSampleState
            the state of the previous sample in the stack. If there is no previous sample, an empty SampleState object
            should be passed in here.
        args : argparse.Namespace
            the command-line arguments provided by the user

        Returns
        -------
        sample : Sample
            the resulting Sample object
        """
        state = RandomJumpSampleState(graph.num_vertices(), prev_state)
        sample_num = int((graph.num_vertices() * (args.sample_size / 100)) / args.sample_iterations)
        sample_num += len(state.sample_idx)
        num_tries = 0
        start = np.random.randint(sample_num)  # start with a random vertex
        vertex = start

        while len(state.index_set) == 0 or len(state.index_set) % sample_num != 0:
            num_tries += 1
            if not state.sampled_marker[vertex]:
                state.index_set.append(vertex)
                state.sampled_marker[vertex] = True
            # If the number of tries is large, or with a probability of 0.15, start from new random vertex
            if num_tries % sample_num == 0 or np.random.random() < 0.15:
                start = np.random.randint(sample_num)
                vertex = start
                num_tries = 0
            elif graph.vertex(vertex).out_degree() > 0:
                # len(graph.get_out_neighbors(vertex)) > 0:  # If the vertex has out neighbors, go to one of them
                vertex = np.random.choice(graph.get_out_neighbors(vertex))
            else:  # Otherwise, restart from the original vertex
                if graph.vertex(start).out_degree() == 0:
                    # len(graph.get_out_neighbors(start)) == 0:  # if original vertex has no out neighbors, change it
                    start = np.random.randint(sample_num)
                vertex = start

        state.sample_idx = np.asarray(state.index_set)
        return Sample(state, graph, old_true_block_assignment)
    # End of random_jump_sample()

    @staticmethod
    def degree_weighted_sample(graph: Graph, assignment: np.ndarray, prev_state: DegreeWeightedSampleState,
                               args: argparse.Namespace) -> 'Sample':
        """Degree-weighted sampling. The probability of selecting a vertex is proportional to its degree.

        Parameters
        ----------
        graph : Graph
            the graph from which to sample vertices
        assignment : np.ndarray[int]
            the vertex-to-community assignment
        prev_state : UniformRandomSampleState
            the state of the previous sample in the stack. If there is no previous sample, an empty SampleState object
            should be passed in here.
        args : argparse.Namespace
            the command-line arguments provided by the user

        Returns
        -------
        sample : Sample
            the resulting Sample object
        """
        state = DegreeWeightedSampleState(graph.num_vertices(), prev_state)
        sample_num = int((graph.num_vertices() * (args.sample_size / 100)) / args.sample_iterations)
        vertex_degrees = np.asarray([graph.vertex(v).in_degree() + graph.vertex(v).out_degree()
                                     for v in graph.vertices()])
        vertex_degrees[state.sample_idx] = 0
        state.sample_idx = np.concatenate(
            (state.sample_idx, np.random.choice(graph.num_vertices(), sample_num, replace=False,
                                                p=vertex_degrees / np.sum(vertex_degrees)))
        )
        return Sample(state, graph, assignment)
    # End of Random_walk_sampling()

    @staticmethod
    def random_node_neighbor_sample(graph: Graph, assignment: np.ndarray, prev_state: RandomNodeNeighborSampleState,
                                    args: argparse.Namespace) -> 'Sample':
        """Random node neighbor sampling. Whenever a single vertex is selected, all its out neighbors are selected
        as well.

        Parameters
        ----------
        graph : Graph
            the graph from which to sample vertices
        assignment : np.ndarray[int]
            the vertex-to-community assignment
        prev_state : UniformRandomSampleState
            the state of the previous sample in the stack. If there is no previous sample, an empty SampleState object
            should be passed in here.
        args : argparse.Namespace
            the command-line arguments provided by the user

        Returns
        -------
        sample : Sample
            the resulting Sample object
        """
        state = RandomNodeNeighborSampleState(graph.num_vertices(), prev_state)
        sample_num = int((graph.num_vertices() * (args.sample_size / 100)) / args.sample_iterations)
        choices = np.setdiff1d(np.asarray(range(graph.num_vertices())), state.sample_idx)
        random_samples = np.random.choice(choices, sample_num, replace=False)
        sample_num += len(state.sample_idx)
        for vertex in random_samples:
            if not state.sampled_marker[vertex]:
                state.index_set.append(vertex)
                state.sampled_marker[vertex] = True
            for neighbor in graph.get_out_neighbors(vertex):
                if not state.sampled_marker[neighbor]:
                    state.index_set.append(neighbor)
                    state.sampled_marker[neighbor] = True
            if len(state.index_set) >= sample_num:
                break
        state.sample_idx = np.asarray(state.index_set[:sample_num])
        return Sample(state, graph, assignment)
    # End of random_node_neighbor_sample()

    @staticmethod
    def forest_fire_sample(graph: Graph, assignment: np.ndarray, prev_state: ForestFireSampleState,
                           args: argparse.Namespace) -> 'Sample':
        """Forest-fire sampling with forward probability = 0.7. At every stage, select 70% of the neighbors of the
        current sample. Vertices that were not selected are 'blacklisted', and no longer viable for future selection.
        If all vertices are thus 'burnt' before the target number of vertices has been selected, restart sampling from
        a new starting vertex.

        Parameters
        ----------
        graph : Graph
            the graph from which to sample vertices
        assignment : np.ndarray[int]
            the vertex-to-community assignment
        prev_state : UniformRandomSampleState
            the state of the previous sample in the stack. If there is no previous sample, an empty SampleState object
            should be passed in here.
        args : argparse.Namespace
            the command-line arguments provided by the user

        Returns
        -------
        sample : Sample
            the resulting Sample object
        """
        state = ForestFireSampleState(graph.num_vertices(), prev_state)
        sample_num = int((graph.num_vertices() * (args.sample_size / 100)) / args.sample_iterations)
        sample_num += len(state.sample_idx)
        while len(state.index_set) == 0 or len(state.index_set) % sample_num != 0:
            for vertex in state.current_fire_front:
                # add vertex to index set
                if not state.sampled_marker[vertex]:
                    state.sampled_marker[vertex] = True
                    state.burnt_marker[vertex] = True
                    state.index_set.append(vertex)
                # select edges to burn
                num_to_choose = np.random.geometric(0.7)
                out_neighbors = graph.get_out_neighbors(vertex)
                if len(out_neighbors) < 1:  # If there are no outgoing neighbors
                    continue
                if len(out_neighbors) <= num_to_choose:
                    num_to_choose = len(out_neighbors)
                mask = np.zeros(len(out_neighbors))
                indexes = np.random.choice(np.arange(len(out_neighbors)), num_to_choose, replace=False)
                mask[indexes] = 1
                for index, value in enumerate(mask):
                    neighbor = out_neighbors[index]
                    if value == 1:  # if chosen, add to next frontier
                        if not state.burnt_marker[neighbor]:
                            state.next_fire_front.append(neighbor)
                    state.burnt_marker[neighbor] = True  # mark all neighbors as visited
            if np.sum(state.burnt_marker) == graph.num_vertices():  # all samples are burnt, restart
                state.burnt_marker = [False] * graph.num_vertices()
                state.current_fire_front = [np.random.randint(graph.num_vertices())]
                state.next_fire_front = list()
                continue
            if len(state.next_fire_front) == 0:  # if fire is burnt-out
                state.current_fire_front = [np.random.randint(graph.num_vertices())]
            else:
                state.current_fire_front = copy(state.next_fire_front)
                state.next_fire_front = list()
        state.sample_idx = np.asarray(state.index_set[:sample_num])
        return Sample(state, graph, assignment)
    # End of forest_fire_sample()

    @staticmethod
    def expansion_snowball_sample(graph: Graph, assignment: np.ndarray, prev_state: ExpansionSnowballSampleState,
                                  args: argparse.Namespace) -> 'Sample':
        """Expansion snowball sampling. At every iteration, picks a vertex adjacent to the current sample that
        contributes the most new neighbors.

        Parameters
        ----------
        graph : Graph
            the graph from which to sample vertices
        assignment : np.ndarray[int]
            the vertex-to-community assignment
        prev_state : UniformRandomSampleState
            the state of the previous sample in the stack. If there is no previous sample, an empty SampleState object
            should be passed in here.
        args : argparse.Namespace
            the command-line arguments provided by the user

        Returns
        -------
        sample : Sample
            the resulting Sample object
        """
        state = ExpansionSnowballSampleState(graph.num_vertices(), prev_state)
        sample_num = int((graph.num_vertices() * (args.sample_size / 100)) / args.sample_iterations)
        sample_num += len(state.sample_idx)
        if not state.neighbors:
            state.neighbors = list(graph.get_out_neighbors(state.start))
            # Set up the initial contributions counts and flag currently neighboring vertices
            for neighbor in graph.get_out_neighbors(state.start):
                state.neighbors_flag[neighbor] = True
                new_neighbors = 0
                for _neighbor in graph.get_out_neighbors(neighbor):
                    if not (state.index_flag[_neighbor] or state.neighbors_flag[_neighbor]):
                        new_neighbors += 1
                state.contribution[neighbor] += new_neighbors
        while len(state.index_set) == 0 or len(state.index_set) % sample_num != 0:
            if len(state.neighbors) == 0 or max(state.contribution) == 0:
                vertex = np.random.choice(list(set(range(graph.num_vertices())) - set(state.index_set)))
                state.index_set.append(vertex)
                for neighbor in graph.get_out_neighbors(vertex):
                    if not state.neighbors_flag[neighbor]:
                        Sample._add_neighbor(neighbor, state.contribution, state.index_flag, state.neighbors_flag,
                                             graph.get_out_neighbors(neighbor), graph.get_in_neighbors(neighbor),
                                             state.neighbors)
                continue
            vertex = np.argmax(state.contribution)
            state.index_set.append(vertex)
            state.index_flag[vertex] = True
            state.neighbors.remove(vertex)
            state.contribution[vertex] = 0
            for neighbor in graph.get_in_neighbors(vertex):
                if not state.neighbors_flag[neighbor]:
                    Sample._add_neighbor(neighbor, state.contribution, state.index_flag, state.neighbors_flag,
                                         graph.get_out_neighbors(neighbor), graph.get_in_neighbors(neighbor),
                                         state.neighbors)
        state.sample_idx = np.asarray(state.index_set)
        return Sample(state, graph, assignment)
    # End of expansion_snowball_sample()

    @staticmethod
    def _add_neighbor(vertex: int, contribution: List[int], index_flag: List[bool], neighbor_flag: List[bool],
                      out_neighbors: np.ndarray, in_neighbors: np.ndarray, neighbors: List[int]):
        #    -> Tuple[List[int], List[bool]]:
        """Updates the expansion contribution for neighbors of a single vertex.
        """
        neighbors.append(vertex)
        neighbor_flag[vertex] = True
        if contribution[vertex] == 0:
            Sample._calculate_contribution(vertex, contribution, index_flag, neighbor_flag, out_neighbors, in_neighbors)
        # return contribution, neighbor_flag
    # End of _add_neighbor()

    @staticmethod
    def _calculate_contribution(vertex: int, contribution: List[int], index_flag: List[bool], neighbor_flag: List[bool],
                                out_neighbors: np.ndarray, in_neighbors: np.ndarray):
        # Compute contribution of this vertex
        for out_neighbor in out_neighbors:
            if not (index_flag[out_neighbor] or neighbor_flag[out_neighbor]):
                contribution[vertex] += 1
        # Decrease contribution of all neighbors with out links to this vertex
        for in_neighbor in in_neighbors:
            if contribution[in_neighbor] > 0:
                contribution[in_neighbor] -= 1
# End of Sample()