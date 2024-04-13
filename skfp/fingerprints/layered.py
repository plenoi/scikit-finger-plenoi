from collections.abc import Sequence
from numbers import Integral
from typing import Optional, Union

import numpy as np
from rdkit.Chem import Mol
from scipy.sparse import csr_array
from sklearn.utils import Interval
from sklearn.utils._param_validation import InvalidParameterError

from skfp.validators import ensure_mols

from .base import FingerprintTransformer


class LayeredFingerprint(FingerprintTransformer):
    """Pattern fingerprint."""

    _parameter_constraints: dict = {
        **FingerprintTransformer._parameter_constraints,
        "fp_size": [Interval(Integral, 1, None, closed="left")],
        "min_path": [Interval(Integral, 1, None, closed="left")],
        "max_path": [Interval(Integral, 1, None, closed="left")],
        "branched_paths": ["boolean"],
    }

    def __init__(
        self,
        fp_size: int = 2048,
        min_path: int = 1,
        max_path: int = 7,
        branched_paths: bool = True,
        sparse: bool = False,
        n_jobs: Optional[int] = None,
        verbose: int = 0,
    ):
        super().__init__(
            n_features_out=fp_size,
            sparse=sparse,
            n_jobs=n_jobs,
            verbose=verbose,
        )
        self.fp_size = fp_size
        self.min_path = min_path
        self.max_path = max_path
        self.branched_paths = branched_paths

    def _validate_params(self) -> None:
        super()._validate_params()
        if self.max_path < self.min_path:
            raise InvalidParameterError(
                f"The max_path parameter of {self.__class__.__name__} must be "
                f"greater or equal to min_path, got: "
                f"min_path={self.min_path}, max_path={self.max_path}"
            )

    def _calculate_fingerprint(
        self, X: Sequence[Union[str, Mol]]
    ) -> Union[np.ndarray, csr_array]:
        from rdkit.Chem.rdmolops import LayeredFingerprint as RDKitLayeredFingerprint

        X = ensure_mols(X)
        X = [
            RDKitLayeredFingerprint(
                x,
                fpSize=self.fp_size,
                minPath=self.min_path,
                maxPath=self.max_path,
                branchedPaths=self.branched_paths,
            )
            for x in X
        ]

        if self.sparse:
            return csr_array(X, dtype=np.uint8)
        else:
            return np.array(X, dtype=np.uint8)