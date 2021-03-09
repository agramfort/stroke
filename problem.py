import functools
import os
from nilearn.image import load_img
import numpy as np
import rampwf as rw
from skimage import metrics
from sklearn.metrics import precision_score, recall_score
from sklearn.model_selection import ShuffleSplit
import warnings

from rampwf.score_types import BaseScoreType
from rampwf.prediction_types.base import BasePrediction


DATA_HOME = 'data'
RANDOM_STATE = 42

# Author: Maria Telenczuk <https://github.com/maikia>
# License: BSD 3 clause


# -------- define the scores --------
def check_mask(mask):
    ''' assert that the given mask consists only of 0s and 1s '''
    assert np.all(np.isin(mask, [0, 1])), ('Cannot compute the score.'
                                           'Found values other than 0s and 1s')


# define the scores
class DiceCoeff(BaseScoreType):
    # Dice’s coefficient (DC), which describes the volume overlap between two
    # segmentations and is sensitive to the lesion size;
    is_lower_the_better = False
    minimum = 0.0
    maximum = 1.0

    def __init__(self, name='dice coeff', precision=3):
        self.name = name
        self.precision = precision

    def __call__(self, y_true_mask, y_pred_mask):
        check_mask(y_true_mask)
        check_mask(y_pred_mask)
        score = self._dice_coeff(y_true_mask, y_pred_mask)
        return score

    def _dice_coeff(self, y_true_mask, y_pred_mask):
        if (not np.any(y_pred_mask)) & (not np.any(y_true_mask)):
            # if there is no true mask in the truth and prediction
            return 1
        else:
            dice = (
                np.sum(np.logical_and(y_pred_mask, y_true_mask) * 2.0) /
                (np.sum(y_pred_mask) + np.sum(y_true_mask))
                )
        return dice


class Precision(BaseScoreType):
    is_lower_the_better = False
    minimum = 0.0
    maximum = 1.0

    def __init__(self, name='precision', precision=3):
        self.name = name
        self.precision = precision

    def __call__(self, y_true_mask, y_pred_mask):
        check_mask(y_true_mask)
        check_mask(y_pred_mask)
        if np.sum(y_pred_mask) == 0 and not np.sum(y_true_mask) == 0:
            return 0.0
        score = precision_score(y_true_mask.ravel(), y_pred_mask.ravel())
        return score


class Recall(BaseScoreType):
    is_lower_the_better = False
    minimum = 0.0
    maximum = 1.0

    def __init__(self, name='recall', precision=3):
        self.name = name
        self.precision = precision

    def __call__(self, y_true_mask, y_pred_mask):
        check_mask(y_true_mask)
        check_mask(y_pred_mask)
        score = recall_score(y_true_mask.ravel(), y_pred_mask.ravel())
        return score


class HausdorffDistance(BaseScoreType):
    # recommened to use 95% percentile Hausdorff Distance which tolerates small
    # otliers
    is_lower_the_better = True
    minimum = 0.0
    maximum = np.inf

    def __init__(self, name='Hausdorff', precision=3):
        self.name = name
        self.precision = precision

    def __call__(self, y_true_mask, y_pred_mask):
        check_mask(y_true_mask)
        check_mask(y_pred_mask)
        score = metrics.hausdorff_distance(y_true_mask, y_pred_mask)
        return score


class AbsoluteVolumeDifference(BaseScoreType):
    is_lower_the_better = True
    minimum = 0.0
    maximum = 1.0

    def __init__(self, name='AVD', precision=3):
        self.name = name
        self.precision = precision

    def __call__(self, y_true_mask, y_pred_mask):
        check_mask(y_true_mask)
        check_mask(y_pred_mask)
        score = np.abs(np.mean(y_true_mask) - np.mean(y_pred_mask))

        return score


# -------- end of define the scores --------
class _MultiClass3d(BasePrediction):
    # y_pred should be 3 dimensional (x_len x y_len x z_len)
    def __init__(self, x_len, y_len, z_len, label_names,
                 y_pred=None, y_true=None, n_samples=None):
        # accepts only the predictions of classes 0 and 1
        self.x_len = x_len
        self.y_len = y_len
        self.z_len = z_len
        self.label_names = label_names

        if y_pred is not None:
            self.y_pred = np.array(y_pred)
        elif y_true is not None:
            self.y_pred = np.array(y_true)
        elif n_samples is not None:
            self.y_pred = np.empty((n_samples,
                                    self.x_len,
                                    self.y_len,
                                    self.z_len), dtype=float)
            self.y_pred.fill(np.nan)
        else:
            raise ValueError(
                'Missing init argument: y_pred, y_true, or n_samples')
        self.check_y_pred_dimensions()

    def check_y_pred_dimensions(self):
        if len(self.y_pred.shape) != 4:
            raise ValueError(
                'Wrong y_pred dimensions: y_pred should be 4D, of size:'
                f'({self.n_samples} x {self.x_len} x {self.y_len}'
                f' x {self.z_len})'
                f'instead its shape is {self.y_pred.shape}')
        if self.y_pred.shape[1:] != (self.x_len, self.y_len, self.z_len):
            raise ValueError(
                'Wrong y_pred dimensions: y_pred should be'
                f' {self.x_len} x {self.y_len} x {self.z_len}'
                f' instead its shape is {self.y_pred.shape}')

    @classmethod
    def combine(cls, predictions_list, index_list=None):
        """Inherits from the base class where the scores are averaged.
        Here, averaged predictions < 0.5 will be set to 0.0 and averaged
        predictions >= 0.5 will be set to 1.0 so that `y_pred` will consist
        only of 0.0s and 1.0s.
        """
        # call the combine from the BasePrediction
        combined_predictions = super(
            _MultiClass3d, cls
            ).combine(
                predictions_list=predictions_list,
                index_list=index_list
                )
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', category=RuntimeWarning)
            combined_predictions.y_pred[
                combined_predictions.y_pred < 0.5] = 0.0
            combined_predictions.y_pred[
                combined_predictions.y_pred >= 0.5] = 1.0

        return combined_predictions

    @property
    def valid_indexes(self):
        """Return valid indices (e.g., a cross-validation slice)."""
        if len(self.y_pred.shape) == 4:
            return ~np.isnan(self.y_pred)
        else:
            raise ValueError('y_pred.shape != 4 is not implemented')

    @property
    def _y_pred_label(self):
        return self.label_names[self.y_pred_label_index]


def _partial_multiclass3d(cls=_MultiClass3d, **kwds):
    # this class partially inititates _MultiClass3d with given
    # keywords
    class _PartialMultiClass3d(_MultiClass3d):
        __init__ = functools.partialmethod(cls.__init__, **kwds)
    return _PartialMultiClass3d


def make_3dmulticlass(x_len, y_len, z_len, label_names):
    return _partial_multiclass3d(x_len=x_len, y_len=y_len, z_len=z_len,
                                 label_names=label_names)


problem_title = 'Stroke Lesion Segmentation'
_prediction_label_names = [0, 1]
_x_len, _y_len, _z_len = 193, 229, 193  # TODO: change the dims
# A type (class) which will be used to create wrapper objects for y_pred
Predictions = make_3dmulticlass(x_len=_x_len, y_len=_y_len, z_len=_z_len,
                                label_names=_prediction_label_names)
# An object implementing the workflow
workflow = rw.workflows.Estimator()

score_types = [
    DiceCoeff(),
    AbsoluteVolumeDifference(),
    # HausdorffDistance(),
    Recall(),
    Precision()
]


# cross validation
def get_cv(X, y):
    test = os.getenv('RAMP_TEST_MODE', 0)
    if test:
        n_splits = 1
    else:
        n_splits = 8
    cv = ShuffleSplit(n_splits=n_splits, test_size=0.2,
                      random_state=RANDOM_STATE)
    return cv.split(X, y)


def _read_data(path, dir_name):
    """
    Read and process data and labels.
    Parameters
    ----------
    path : path to directory that has 'data' subdir
    typ : {'train', 'test'}
    Returns
    -------
    X, y data
    """

    dir_data = os.path.join(path, dir_name)
    list_subj_dirs = os.listdir(dir_data)
    test = os.getenv('RAMP_TEST_MODE', 0)
    if test:
        # use only 5 subjects, otherwise take all
        list_subj_dirs = list_subj_dirs[:3]

    n_samples = len(list_subj_dirs)
    # we will be loading only the directory paths
    X = np.empty(n_samples, dtype='<U128')
    # we will be loading all the lesions arrays in
    y = np.empty((n_samples, _x_len, _y_len, _z_len))

    for idx, next_subj in enumerate(list_subj_dirs):
        X[idx] = os.path.join(dir_data, next_subj, 'T1.nii.gz')
        y_path = os.path.join(dir_data, next_subj, 'truth.nii.gz')
        y[idx, :] = load_img(y_path).get_fdata()
        # make sure that all the elements of y are in _prediction_label_names
        assert np.all(np.in1d(y, np.array(_prediction_label_names)))
    return X, y


def get_train_data(path='.'):
    path = os.path.join(path, DATA_HOME)
    return _read_data(path, 'train')


def get_test_data(path="."):
    path = os.path.join(path, DATA_HOME)
    return _read_data(path, 'test')
