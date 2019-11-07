"""Holds information about graphs loaded from .tsv files.
"""

import os
import sys
from typing import List, Optional, Tuple, Dict
import argparse
import csv

import numpy as np
import pandas as pd

from sample import Sample
from samplestate import SampleState


class Graph():
    """Holds the graph variables that do not change due to partitioning.
    """

    def __init__(self, out_neighbors: List[np.ndarray], in_neighbors: List[np.ndarray], num_nodes: int, num_edges: int,
        true_block_assignment: np.ndarray = None) -> None:
        """Creates a new Graph object.

            Parameters
            ---------
            out_neighbors : List[np.ndarray]
                    the outgoing edges from each node
            in_neighbors : List[np.ndarray]
                    the incoming edges to each node
            num_nodes : int
                    the number of nodes in the graph
            num_edges : int
                    the number of edges in the graph
            true_block_assignment : np.ndarray, optional
                    the true partitioning of the graph, if known
        """
        self.out_neighbors = out_neighbors
        self.in_neighbors = in_neighbors
        self.num_nodes = num_nodes
        self.num_edges = num_edges
        self.true_block_assignment = true_block_assignment
    # End of __init__()
    
    def update(self, graph: 'Graph'):
        """Updates the current graph with the incoming graph's variables. Used when loading the graph.

            Parameters
            ---------
            graph : Graph
                    the new, updated graph
        """
        self.out_neighbors = graph.out_neighbors
        self.in_neighbors = graph.in_neighbors
        self.num_nodes = graph.num_nodes
        self.num_edges = graph.num_edges
    # End of update()

    @staticmethod
    def load(args: argparse.Namespace) -> 'Graph':
        """Loads a Graph object from file. Assumes that the true partition is available.

            Parameters
            ---------
            args : Namespace
                    the parsed command-line arguments
            
            Returns
            ------
            graph : Graph
                    the loaded Graph object
        """
        has_truth = not args.notruth
        print("has truth = ", has_truth)
        input_filename = _build_filepath(args)
        if args.parts >= 1:
            print('\nLoading partition 1 of {} ({}) ...'.format(args.parts, input_filename + "_1.tsv"))
            graph = _load_graph(input_filename, load_true_partition=has_truth, part_num=1)
            for part in range(2, args.parts + 1):
                print('Loading partition {} of {} ({}) ...'.format(part, args.parts, input_filename + "_" + str(part) + ".tsv"))
                graph.update(_load_graph(input_filename, load_true_partition=False, part_num=part, graph=graph))
        else:
            graph = _load_graph(input_filename, load_true_partition=has_truth)

        if args.verbose:
            print('Number of nodes: {}'.format(graph.num_nodes))
            print('Number of edges: {}'.format(graph.num_edges))
        if args.degrees:
            _save_degree_distribution(args, graph.out_neighbors, graph.in_neighbors)
        return graph
    # End of load()

    def sample(self, args: argparse.Namespace, prev_state: SampleState = None) -> Tuple['Graph', Sample]:
        """Sample a set of vertices from the graph.

            Parameters
            ----------
            args : Namespace
                    the parsed command-line arguments

            Returns
            ------
            subgraph : Graph
                    the subgraph created from the sampled Graph vertices
            sample : Sample
                    the sample object containing the vertex and block mappings
        """
        sample_size = int((self.num_nodes * (args.sample_size / 100)) / args.sample_iterations)
        if prev_state is None:
            prev_state = SampleState(sample_size)
        sample_object = Sample.create_sample(self.num_nodes, self.out_neighbors, self.in_neighbors,
                                             self.true_block_assignment, args, prev_state)
        subgraph = Graph(sample_object.out_neighbors, sample_object.in_neighbors, sample_object.sample_num,
                         sample_object.num_edges, sample_object.true_block_assignment)
        return subgraph, sample_object
    # End of sample()

    def sample_from_vertex_ids(self, vertices: np.ndarray, args: argparse.Namespace) -> Tuple['Graph', Sample]:
        """Creates a sample using pre-determined vertex IDs.
        """
        state = SampleState(len(vertices))
        state.sample_idx = vertices
        sample_object = Sample(state, self.out_neighbors, self.in_neighbors, self.true_block_assignment)
        subgraph = Graph(sample_object.out_neighbors, sample_object.in_neighbors, len(vertices),
                         sample_object.num_edges, sample_object.true_block_assignment)
        return subgraph, sample_object
    # End of sample_from_vertex_ids()
# End of Graph()


def _build_filepath(args: argparse.Namespace) -> str:
    """Builds the filename string.

        Parameters
        ---------
        args : argparse.Namespace
                the command-line arguments passed in
        
        Returns
        ------
        filepath : str
                the path to the dataset base directory
    """
    filepath_base = "{0}/{1}/{2}Overlap_{3}BlockSizeVar/{1}_{2}Overlap_{3}BlockSizeVar_{4}_nodes".format(
        args.directory, args.type, args.overlap, args.blockSizeVar, args.numNodes
    )

    if not os.path.isfile(filepath_base + '.tsv') and not os.path.isfile(filepath_base + '_1.tsv'):
        print("File doesn't exist: '{}'!".format(filepath_base))
        sys.exit(1)
        
    return filepath_base
# End of build_filepath()


def _load_graph(input_filename: str, load_true_partition: bool, part_num: Optional[int] = None, 
    graph: Optional[Graph] = None) -> Graph:
    """Load the graph from a TSV file with standard format, and the truth partition if available

        Parameters
        ----------
        input_filename : str
                input file name not including the .tsv extension
        true_partition_available : bool
                whether the truth partition is available
        part_num : int, optional
                specify which stage of the streaming graph to load
        graph : Graph, optional
                existing graph to add to. This is used when loading the streaming graphs one stage at a time. Note that
                the truth partition is loaded all together at once.

        Returns
        -------
        graph : Graph
                the Graph object loaded or updated from file

        Notes
        -----
        The standard tsv file has the form for each row: "from to [weight]" (tab delimited). Nodes are indexed from 0
        to N-1. If available, the true partition is stored in the file `filename_truePartition.tsv`.
    """
    # read the entire graph CSV into rows of edges
    if (part_num == None):
        edge_rows = pd.read_csv('{}.tsv'.format(input_filename), delimiter='\t', header=None).values
    else:
        edge_rows = pd.read_csv('{}_{}.tsv'.format(input_filename, part_num), delimiter='\t', header=None).values

    if (graph == None):  # no previously loaded streaming pieces
        N = edge_rows[:, 0:2].max()  # number of nodes
        out_neighbors = [[] for i in range(N)]
        in_neighbors = [[] for i in range(N)]
    else:  # add to previously loaded streaming pieces
        N = max(edge_rows[:, 0:2].max(), len(graph.out_neighbors))  # number of nodes
        out_neighbors = [list(graph.out_neighbors[i]) for i in range(len(graph.out_neighbors))]
        out_neighbors.extend([[] for i in range(N - len(out_neighbors))])
        in_neighbors = [list(graph.in_neighbors[i]) for i in range(len(graph.in_neighbors))]
        in_neighbors.extend([[] for i in range(N - len(in_neighbors))])
    weights_included = edge_rows.shape[1] == 3

    # load edges to list of lists of out and in neighbors
    for i in range(edge_rows.shape[0]):
        if weights_included:
            edge_weight = edge_rows[i, 2]
        else:
            edge_weight = 1
        # -1 on the node index since Python is 0-indexed and the standard graph TSV is 1-indexed
        out_neighbors[edge_rows[i, 0] - 1].append([edge_rows[i, 1] - 1, edge_weight])
        in_neighbors[edge_rows[i, 1] - 1].append([edge_rows[i, 0] - 1, edge_weight])

    # convert each neighbor list to neighbor numpy arrays for faster access
    for i in range(N):
        if len(out_neighbors[i]) > 0:
            out_neighbors[i] = np.array(out_neighbors[i], dtype=int)
        else:
            out_neighbors[i] = np.array(out_neighbors[i], dtype=int).reshape((0,2))
    for i in range(N):
        if len(in_neighbors[i]) > 0:
            in_neighbors[i] = np.array(in_neighbors[i], dtype=int)
        else:
            in_neighbors[i] = np.array(in_neighbors[i], dtype=int).reshape((0,2))

    E = sum(len(v) for v in out_neighbors)  # number of edges

    if load_true_partition:
        # read the entire true partition CSV into rows of partitions
        true_b_rows = pd.read_csv('{}_truePartition.tsv'.format(input_filename), delimiter='\t',
                                  header=None).values
        true_b = np.ones(true_b_rows.shape[0], dtype=int) * -1  # initialize truth assignment to -1 for 'unknown'
        for i in range(true_b_rows.shape[0]):
            true_b[true_b_rows[i, 0] - 1] = int(
                true_b_rows[i, 1] - 1)  # -1 since Python is 0-indexed and the TSV is 1-indexed

    if load_true_partition:
        return Graph(out_neighbors, in_neighbors, N, E, true_b)
    else:
        return Graph(out_neighbors, in_neighbors, N, E)
# End of load_graph()


def _save_degree_distribution(args: argparse.Namespace, out_neighbors: List[np.ndarray],
    in_neighbors: List[np.ndarray]):
    """Saves the in and out degrees of all vertices in the graph.

    Parameters
    ----------
    args : argparse.Namespace
        the command-line arguments provided
    out_neighbors : List[np.ndarray]
        the outgoing edges from each node
    in_neighbors : List[np.ndarray]
        the incoming edges to each node
    """
    write_header = False
    if not os.path.isfile(args.csv + ".csv"):
        directory = os.path.dirname(args.csv + ".csv")
        if directory not in [".", ""]:
            os.makedirs(directory, exist_ok=True)
        write_header = True
    num_vertices = len(out_neighbors)
    out_degrees = [len(neighbors) for neighbors in out_neighbors]
    in_degrees = [len(neighbors) for neighbors in in_neighbors]
    with open(args.csv + ".csv", "a") as details_file:
        writer = csv.writer(details_file)
        if write_header:
            writer.writerow(["Num Vertices", "In/Out", "Degree"])
        for degree in out_degrees:
            writer.writerow([num_vertices, "Out", degree])
        for degree in in_degrees:
            writer.writerow([num_vertices, "In", degree])
    exit()
# End of _save_degree_distribution()
