import os
from time import time
from typing import Callable, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rdkit.Chem.rdFingerprintGenerator as fpgens
from e3fp.conformer.generate import (
    FORCEFIELD_DEF,
    MAX_ENERGY_DIFF_DEF,
    NUM_CONF_DEF,
    POOL_MULTIPLIER_DEF,
    RMSD_CUTOFF_DEF,
)
from e3fp.conformer.generator import ConformerGenerator
from e3fp.pipeline import fprints_from_mol
from joblib import cpu_count
from ogb.graphproppred import GraphPropPredDataset
from rdkit import Chem
from rdkit.Chem import MolFromSmiles
from rdkit.Chem.PropertyMol import PropertyMol
from rdkit.Chem.rdMolDescriptors import GetMACCSKeysFingerprint
from rdkit.Chem.rdReducedGraphs import GetErGFingerprint
from scipy.sparse import csr_array, vstack

from base import FingerprintTransformer
from featurizers.fingerprints import (
    E3FP,
    MHFP,
    AtomPairFingerprint,
    ERGFingerprint,
    MACCSKeysFingerprint,
    MAP4Fingerprint,
    MorganFingerprint,
    TopologicalTorsionFingerprint,
)
from featurizers.map4_mhfp_helper_functions import (
    get_map4_fingerprint,
    get_mhfp,
)

dataset_name = "ogbg-molhiv"

# N_SPLITS - number of parts in which the dataset will be divided.
# the test is performed first on 1 of them, then 2, ... then N_SPLITS
# testing different sizes of input data
N_SPLITS = 5
# N_REPEATS - number of test repetitions - for getting average time score
N_REPEATS = 5
MAX_CORES = cpu_count()
N_CORES = [2**i for i in range(MAX_CORES.bit_length())]
if MAX_CORES > N_CORES[-1]:
    N_CORES.append(MAX_CORES)
COUNT_TYPES = [False, True]
SPARSE_TYPES = [False, True]
PLOT_DIR = "./benchmark_times_plotted"
SCORE_DIR = "./benchmark_times_saved"


def get_times_emf(
    X: pd.DataFrame, transformer_function: FingerprintTransformer, **kwargs
):
    if "count" in kwargs:
        count = kwargs["count"]
        print(f" - - count: {count}")

    n_jobs = kwargs["n_jobs"]
    print(f" - - n_jobs: {n_jobs}")

    n_molecules = X.shape[0]
    emf_transformer = transformer_function(**kwargs)

    # testing for different sizes of input datasets
    result = []
    for data_fraction in np.linspace(0, 1, N_SPLITS + 1)[1:]:
        print(f" - - - dataset fraction: {int(100*data_fraction)}%")
        n = int(n_molecules * data_fraction)
        subset = X[:n]
        times = [None for _ in range(N_REPEATS)]
        # testing several times to get average computation time
        for i in range(N_REPEATS):
            print(f" - - - - repeat: {i}/{N_REPEATS-1}")
            start = time()
            X_transformed = emf_transformer.transform(subset)
            end = time()
            times[i] = end - start
        result.append(np.mean(times))
    return np.array(result)


def get_all_times_emf(X, fingerprint_transformer, use_count: bool = True):
    print(" - scikit-fingerprints")
    times = [
        [
            get_times_emf(
                X,
                fingerprint_transformer,
                count=count,
                n_jobs=n_cores,
            )
            for n_cores in N_CORES
        ]
        for count in (COUNT_TYPES if use_count else [None])
    ]
    if use_count:
        return times
    return times[0]


def get_generator_times_rdkit(X: pd.DataFrame, generator: object, count: bool):
    print(f" - - count: {count}")
    n_molecules = X.shape[0]
    if count:
        fp_function = lambda x: generator.GetCountFingerprint(
            MolFromSmiles(x)
        ).ToList()
    else:
        fp_function = lambda x: generator.GetFingerprint(MolFromSmiles(x))

    # testing for different sizes of input datasets
    result = []
    for data_fraction in np.linspace(0, 1, N_SPLITS + 1)[1:]:
        print(f" - - - dataset fraction: {int(100*data_fraction)}%")
        n = int(n_molecules * data_fraction)
        subset = X[:n]
        times = [None for _ in range(N_REPEATS)]
        # testing several times to get average computation time
        for i in range(N_REPEATS):
            print(f" - - - - repeat: {i}/{N_REPEATS-1}")
            start = time()
            X_transformed = np.array([fp_function(x) for x in subset])
            end = time()
            times[i] = end - start
        result.append(np.mean(times))
    return np.array(result)


def get_all_generator_times_rdkit(X, generator):
    print(" - generator")
    return [
        get_generator_times_rdkit(
            X,
            generator,
            count=count,
        )
        for count in COUNT_TYPES
    ]


def get_times_sequential(X: pd.DataFrame, func: Callable, **kwargs):
    if "count" in kwargs:
        count = kwargs["count"]
        print(f" - - count: {count}")

    n_molecules = X.shape[0]
    # testing for different sizes of input datasets
    result = []
    for data_fraction in np.linspace(0, 1, N_SPLITS + 1)[1:]:
        print(f" - - - dataset fraction: {int(100*data_fraction)}%")
        n = int(n_molecules * data_fraction)
        subset = X[:n]
        times = [None for _ in range(N_REPEATS)]
        # testing several times to get average computation time
        for i in range(N_REPEATS):
            print(f" - - - - repeat: {i}/{N_REPEATS-1}")
            start = time()
            X_transformed = np.array(
                [func(MolFromSmiles(x), **kwargs) for x in subset]
            )
            end = time()
            times[i] = end - start
        result.append(np.mean(times))
    return np.array(result)


def get_all_sequential_times(
    X, fingerprint_function, use_count: bool = True, **kwargs
):
    print(" - sequential")
    times = [
        get_times_sequential(X, fingerprint_function, count=count, **kwargs)
        if use_count
        else get_times_sequential(X, fingerprint_function, **kwargs)
        for count in (COUNT_TYPES if use_count else [None])
    ]
    if use_count:
        return times
    return times[0]


def get_times_e3fp(X: pd.DataFrame):
    confgen_params = {
        "first": 1,
        "num_conf": NUM_CONF_DEF,
        "pool_multiplier": POOL_MULTIPLIER_DEF,
        "rmsd_cutoff": RMSD_CUTOFF_DEF,
        "max_energy_diff": MAX_ENERGY_DIFF_DEF,
        "forcefield": FORCEFIELD_DEF,
        "get_values": True,
        "seed": 0,
    }
    fprint_params = {
        "bits": 4096,
        "radius_multiplier": 1.5,
        "rdkit_invariants": True,
    }

    n_molecules = X.shape[0]
    # testing for different sizes of input datasets
    result = []
    for data_fraction in np.linspace(0, 1, N_SPLITS + 1)[1:]:
        n = int(n_molecules * data_fraction)
        subset = X[:n]
        times = [None for _ in range(N_REPEATS)]
        # testing several times to get average computation time
        for i in range(N_REPEATS):
            start = time()
            X_seq = []
            conf_gen = ConformerGenerator(**confgen_params)
            for smiles in X:
                # creating molecule object
                mol = Chem.MolFromSmiles(smiles)
                mol.SetProp("_Name", smiles)
                mol = PropertyMol(mol)
                mol.SetProp("_SMILES", smiles)

                # getting a molecule and the fingerprint
                mol, values = conf_gen.generate_conformers(mol)
                fps = fprints_from_mol(mol, fprint_params=fprint_params)

                # chose the fingerprint with the lowest energy
                energies = values[2]
                fp = fps[np.argmin(energies)].fold(1024)

                X_seq.append(fp.to_vector())
            X_seq = np.array([fp.toarray().squeeze() for fp in X_seq])
            end = time()
            times[i] = end - start
        result.append(np.mean(times))
    return np.array(result)


def save_results(
    n_molecules: int,
    y_emf: List,
    y_rdkit: List,
    title: str = "",
    count: bool = None,
    save: bool = True,
):
    if count:
        title += " count"
    elif count is not None:
        title += " bit"

    X = n_molecules * np.linspace(0, 1, N_SPLITS + 1)[1:]

    plt.rcParams["font.size"] = 20
    fig = plt.figure(figsize=(15, 10))
    ax1 = fig.add_subplot()
    ax1.set_title(title)

    for i, y in zip(N_CORES, y_emf):
        ax1.plot(X, y, label=f"scikit-fingerprints time - {i} cores")

    ax1.plot(X, y_rdkit, label="sequential time")

    ax1.set_ylabel("Time of computation [s]")
    ax1.set_xlabel("Number of fingerprints")

    ax1.set_xlim(n_molecules * 0.1, n_molecules * 1.1)
    ax1.set_ylim(bottom=0)

    plt.legend(loc="upper left", fontsize="8")

    to_save = np.object_([y_rdkit, y_emf])
    np.save(SCORE_DIR + "/" + title.replace(" ", "_") + ".npy", to_save)

    if save:
        plt.savefig(PLOT_DIR + "/" + title.replace(" ", "_") + ".png")
    else:
        plt.show()
    plt.close(fig)


def save_all_results(
    scores_emf: List,
    scores_seq: List,
    n_molecules: int,
    title: str,
    use_count: bool,
):
    if use_count:
        for i, count in enumerate(COUNT_TYPES):
            save_results(
                n_molecules,
                scores_emf[i],
                scores_seq[i],
                title=title,
                count=count,
            )
    else:
        save_results(
            n_molecules,
            scores_emf,
            scores_seq,
            title=title,
            count=None,
        )


if __name__ == "__main__":
    full_time_start = time()

    if not os.path.exists(PLOT_DIR):
        os.mkdir(PLOT_DIR)

    if not os.path.exists(SCORE_DIR):
        os.mkdir(SCORE_DIR)

    GraphPropPredDataset(name=dataset_name, root="../dataset")
    dataset = pd.read_csv(
        f"../dataset/{'_'.join(dataset_name.split('-'))}/mapping/mol.csv.gz"
    )
    X = dataset["smiles"]
    y = dataset["HIV_active"]

    n_molecules = X.shape[0]

    # MORGAN FINGERPRINT
    print("Morgan")
    morgan_emf_times = get_all_times_emf(X, MorganFingerprint)
    generator = fpgens.GetMorganGenerator()
    morgan_rdkit_times = get_all_generator_times_rdkit(X, generator)
    save_all_results(
        morgan_emf_times,
        morgan_rdkit_times,
        n_molecules,
        "Morgan Fingerprint",
        True,
    )

    # ATOM PAIR FINGERPRINT
    print("Atom Pair")
    atom_pair_emf_times = get_all_times_emf(X, AtomPairFingerprint)
    generator = fpgens.GetAtomPairGenerator()
    atom_pair_rdkit_times = get_all_generator_times_rdkit(X, generator)
    save_all_results(
        atom_pair_emf_times,
        atom_pair_rdkit_times,
        n_molecules,
        "Atom Pair Fingerprint",
        True,
    )

    # TOPOLOGICAL TORSION FINGERPRINT
    print("Topological Torsion")
    topological_torsion_emf_times = get_all_times_emf(
        X, TopologicalTorsionFingerprint
    )
    generator = fpgens.GetTopologicalTorsionGenerator()
    topological_torsion_rdkit_times = get_all_generator_times_rdkit(
        X, generator
    )
    save_all_results(
        topological_torsion_emf_times,
        topological_torsion_rdkit_times,
        n_molecules,
        "Topological Torsion Fingerprint",
        True,
    )

    # MACCS KEYS FINGERPRINT
    print("MACCS Keys")
    MACCSKeys_emf_times = get_all_times_emf(X, MACCSKeysFingerprint, False)
    MACCSKeys_rdkit_times = get_all_sequential_times(
        X, GetMACCSKeysFingerprint, False
    )
    save_all_results(
        MACCSKeys_emf_times,
        MACCSKeys_rdkit_times,
        n_molecules,
        "MACCS Keys fingerprint",
        False,
    )

    # ERG FINGERPRINT
    print("ERG")
    ERG_emf_times = get_all_times_emf(X, ERGFingerprint, False)
    ERG_rdkit_times = get_all_sequential_times(X, GetErGFingerprint, False)
    save_all_results(
        ERG_emf_times, ERG_rdkit_times, n_molecules, "ERG fingerprint", False
    )

    # MAP4 FINGERPRINT
    print("MAP4")
    MAP4_emf_times = get_all_times_emf(X, MAP4Fingerprint)
    MAP4_sequential_times = get_all_sequential_times(X, get_map4_fingerprint)
    save_all_results(
        MAP4_emf_times,
        MAP4_sequential_times,
        n_molecules,
        "MAP4 fingerprint",
        True,
    )

    # MHFP FINGERPRINT
    print("MHFP")
    MHFP_emf_times = get_all_times_emf(X, MHFP)
    MHFP_sequential_times = get_all_sequential_times(X, get_mhfp)
    save_all_results(
        MHFP_emf_times, MHFP_sequential_times, n_molecules, "MHFP", True
    )

    # E3FP_emf_times = get_all_times_emf(X, E3FP, False)
    # E3FP_sequential_times = [
    #     get_times_e3fp(X, sparse=sparse) for sparse in SPARSE_TYPES
    # ]
    #
    # save_all_results(
    #     E3FP_emf_times,
    #     E3FP_sequential_times,
    #     n_molecules,
    #     "E3FP fingerprint",
    #     False,
    # )

    full_time_end = time()
    print("Time of execution: ", full_time_end - full_time_start, "s")