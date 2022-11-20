import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
import logging
from joblib import dump, load
import sys
from pathlib import Path
from typing import Dict, Optional, Any, Iterable, Callable, Union, Tuple

from sklearn.metrics import (
    balanced_accuracy_score,
    f1_score,
    confusion_matrix,
    classification_report,
    accuracy_score,
    mean_absolute_error,
    roc_auc_score,
    RocCurveDisplay,
    mean_squared_error,
    log_loss,
    auc,
    roc_curve,
)
from sklearn.model_selection import (
    GridSearchCV,
    RandomizedSearchCV,
    StratifiedShuffleSplit,
)

from mlexpy.pipeline_utils import MLSetup, ExperimentSetup, cv_report
from mlexpy.utils import make_directory


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ExperimentBase:
    def __init__(
        self,
        train_setup: MLSetup,
        test_setup: MLSetup,
        cv_split_count: int = 5,
        rnd_int: int = 100,
        model_dir: Optional[Union[str, Path]] = None,
        model_storage_function: Optional[Callable] = None,
        model_loading_function: Optional[Callable] = None,
        model_tag: str = "_development",
        process_tag: str = "_development",
    ) -> None:
        self.testing = test_setup
        self.training = train_setup
        self.processor = None
        self.test_cv_split = 0.4
        self.rnd = np.random.RandomState(rnd_int)
        self.cv_split_count = cv_split_count
        self.metric_dict: Dict[str, Callable] = {}
        self.standard_metric = ""
        self.process_tag = process_tag
        self.model_tag = model_tag

        # Setup model io
        if not model_storage_function:
            logger.info(
                "No model storage function provided. Using the default class method (joblib, or .store_model native method)."
            )
            self.store_model = self.default_store_model
        else:
            logger.info(f"Set the model storage function as: {model_storage_function}")
            self.store_model = model_storage_function
        if not model_loading_function:
            logger.info(
                "No model loading function provided. Using the default class method (joblib, or .load_model native method)."
            )
            self.load_model = self.default_load_model
        else:
            logger.info(f"Set the model loading function as: {model_loading_function}")
            self.store_model = model_loading_function

        if not model_dir:
            logger.info(
                f"No model location provided. Creating a .models/ at: {sys.path[-1]}"
            )
            self.model_dir = Path(sys.path[-1]) / ".models" / self.process_tag
        elif isinstance(model_dir, str):
            logger.info(
                f"setting the model path to {model_dir}. (Converting from string to pathlib.Path)"
            )
            self.model_dir = Path(model_dir) / self.process_tag
        else:
            logger.info(
                f"setting the model path to {model_dir}. (Converting from string to pathlib.Path)"
            )
            self.model_dir = model_dir / self.process_tag

    def make_storage_dir(self) -> None:
        """If we dont yet have the storage directory, make it now"""
        if not self.model_dir.is_dir():
            make_directory(self.model_dir)

    def process_data(
        self, process_method_str: str = "process_data", from_file: bool = False
    ) -> ExperimentSetup:
        raise NotImplementedError("This needs to be implemented in the child class.")

    def process_data_from_stored_models(self) -> ExperimentSetup:
        """Here perform all data processing using models loaded from storage."""

        from_file_processed_data = self.process_data(from_file=True)
        return from_file_processed_data

    def train_model(
        self,
        model: Any,
        full_setup: ExperimentSetup,
        cv_model: str = "random_search",
        cv_iterations: int = 20,
        params: Optional[Dict[str, Any]] = None,
    ):
        if params:
            model = self.cv_search(
                full_setup.train_data,
                model,
                params,
                cv_model=cv_model,
                random_iterations=cv_iterations,
            )
        else:
            logger.info("Performing standard model training.")
            model.fit(full_setup.train_data.obs, full_setup.train_data.labels)

        logger.info("Model trained")
        return model

    def predict(
        self, full_setup: ExperimentSetup, model: Any, proba: bool = False
    ) -> Any:
        if proba:
            return model.predict_proba(full_setup.test_data.obs)
        else:
            return model.predict(full_setup.test_data.obs)

    def evaluate_predictions(
        self,
        full_setup: ExperimentSetup,
        predictions: Iterable,
        class_probabilities: Optional[Iterable] = None,
        baseline_prediction: bool = False,
    ) -> Dict[str, float]:
        raise NotImplementedError("This needs to be implemented in the child class.")

    def cv_splits(self, n_splits: int = 5) -> StratifiedShuffleSplit:
        """Creates an object to be passed to cv_eval, allowing for
        # identical splits everytime cv_eval is used.
        """
        return StratifiedShuffleSplit(
            n_splits=n_splits, test_size=self.test_cv_split, random_state=self.rnd
        )

    def cv_search(
        self,
        data_setup: MLSetup,
        ml_model: Any,
        parameters: Dict[str, Any],
        cv_model: str = "random_search",
        random_iterations: int = 5,
    ) -> Any:
        """Run grid cross_validation search over the parameter space.
        If no GirdSearch model provided run random search
        """

        if not self.standard_metric:
            raise NotImplementedError(
                "No standard_metric has been set. This is likely because the ExperimentBase is being called, instead of being inherited. Try using the ClassifierExpirament or RegressionExpirament, or build a child class to inherit the ExpiramentBase."
            )

        if cv_model == "grid_search":
            cv_search = GridSearchCV(
                ml_model,
                parameters,
                scoring=self.standard_metric,
                cv=self.cv_splits(self.cv_split_count),
                n_jobs=1,
            )
        else:
            cv_search = RandomizedSearchCV(
                ml_model,
                parameters,
                n_iter=random_iterations,
                scoring=self.standard_metric,
                cv=self.cv_splits(self.cv_split_count),
                verbose=2,
                refit=True,
                n_jobs=1,
            )
        logger.info(f"Beginning CV search using {cv_model} ...")
        cv_search.fit(data_setup.obs, data_setup.labels)
        logger.info(cv_report(cv_search.cv_results_))
        return cv_search.best_estimator_

    def add_metric(self, metric: Callable, name: str) -> None:
        """Add the provided metric to the metric_dict"""
        self.metric_dict[name] = metric

    def remove_metric(self, name: str) -> None:
        """Add the provided metric to the metric_dict"""
        del self.metric_dict[name]

    def default_store_model(self, model: Any) -> None:
        """Given a calculated model, store it locally using joblib.
        Longer term/other considerations can be found here: https://scikit-learn.org/stable/model_persistence.html
        """
        self.make_storage_dir()

        if hasattr(model, "save_model"):
            # use the model's saving utilities, specifically beneficial wish xgboost. Can be beneficial here to use a json
            logger.info(f"Found a save_model method in {model}")
            model_path = self.model_dir / f"{self.model_tag}.json"
            model.save_model(model_path)
        else:
            logger.info(f"Saving the {model} model using joblib.")
            model_path = self.model_dir / f"{self.model_tag}.joblib"
            dump(model, model_path)
        logger.info(f"Dumped {self.model_tag} to: {model_path}")

    def default_load_model(self, model: Optional[Any] = None) -> Any:
        """Given a model name, load it from storage."""

        if hasattr(model, "load_model") and model:
            # use the model's loading utilities -- specifically beneficial with xgboost
            logger.info(f"Found a load_model method in {model}")
            model_path = self.model_dir / f"{self.model_tag}.json"
            logger.info(f"Loading {self.model_tag} from: {model_path}")
            loaded_model = model.load_model(model_path)
        else:
            model_path = self.model_dir / f"{self.model_tag}.joblib"
            logger.info(f"Loading {self.model_tag} from: {model_path}")
            loaded_model = load(model_path)
        logger.info(f"Retrieved {self.model_tag} from: {model_path}")
        return loaded_model


class ClassifierExperimentBase(ExperimentBase):
    def __init__(
        self,
        train_setup: MLSetup,
        test_setup: MLSetup,
        cv_split_count: int = 5,
        rnd_int: int = 100,
        model_dir: Optional[Union[str, Path]] = None,
        model_storage_function: Optional[Callable] = None,
        model_loading_function: Optional[Callable] = None,
        model_tag: str = "_development",
        process_tag: str = "_development",
    ) -> None:
        super().__init__(
            train_setup,
            test_setup,
            cv_split_count,
            rnd_int,
            model_dir,
            model_storage_function,
            model_loading_function,
            model_tag,
            process_tag,
        )
        self.baseline_value = None  # to be implemented in the child class
        self.standard_metric = "f1_macro"
        self.metric_dict = {
            "f1": f1_score,
            "log_loss": log_loss,
            "balanced_accuracy": balanced_accuracy_score,
            "accuracy": accuracy_score,
            "confusion_matrix": confusion_matrix,
            "classification_report": classification_report,
        }

    def evaluate_predictions(
        self,
        labels: Iterable,
        predictions: Iterable,
        class_probabilities: Optional[Iterable] = None,
        baseline_prediction: bool = False,
    ) -> Dict[str, float]:
        """Evaluate all predictions, and return the results in a dict"""

        if baseline_prediction:
            if not self.baseline_value:
                raise ValueError(
                    "No baseline value was provided to the class and a baseline evaluation was called. Either set a baseline value or pass baseline_prediction=False to evaluate_predictions method."
                )
            evaluation_prediction = self.baseline_value
        else:
            evaluation_prediction = predictions

        result_dict: Dict[str, float] = {}
        # First test the predictions in the metric dictionary...
        for name, metric in self.metric_dict.items():
            if "f1" in name:
                result_dict[name + "_macro"] = metric(
                    labels, evaluation_prediction, average="macro"
                )
                result_dict[name + "_micro"] = metric(
                    labels, evaluation_prediction, average="micro"
                )
                result_dict[name + "_weighted"] = metric(
                    labels,
                    evaluation_prediction,
                    average="weighted",
                )
            else:
                try:
                    result_dict[name] = metric(labels, evaluation_prediction)
                except ValueError:
                    # See if we would succeed with using the class probabilities
                    try:
                        result_dict[name] = metric(labels, class_probabilities)
                    except ValueError:
                        print(f"Unknown issues with the {name} metric evaluation.")

        for name, score in result_dict.items():
            print(f"\nThe {name} score is: \n {score}.")

        return result_dict

    def evaluate_roc_metrics(
        self,
        full_setup: ExperimentSetup,
        class_probabilities: np.ndarray,
        model: Any,
    ) -> Dict[str, float]:
        """Perform any roc metric evaluation here. These require prediction probabilities or confidence, thus are separate
        from more standard prediction value based metrics."""

        # First, check that there are more than 1 predictions
        if len(class_probabilities) <= 1:
            raise ValueError(
                f"The class_probabilities passed to evaluate_roc_metrics is only 1 record class_probabilities.shape = {class_probabilities.shape}"
            )

        result_dict: Dict[str, float] = {}
        # Need to determine if using a multiclass or binary classification experiment
        if len(class_probabilities[0]) <= 2:
            logger.info("Computing the binary AU-ROC curve scores.")
            # Then this is binary classification. Note from sklearn docs: The probability estimates correspond
            # to the **probability of the class with the greater label**
            result_dict["roc_auc_score"] = roc_auc_score(
                y_true=full_setup.test_data.labels,
                y_score=class_probabilities[:, 1],
            )
            print(f"""\nThe ROC AUC score is: {result_dict["roc_auc_score"]}""")

            dsp = RocCurveDisplay.from_estimator(
                estimator=model,
                X=full_setup.test_data.obs,
                y=full_setup.test_data.labels,
            )
            dsp.plot()
            plt.show()

        else:
            logger.info("Computing the multi-class AU-ROC curve scores.")
            # We are doing multiclass classification and need to use more parameters to calculate the roc
            result_dict["roc_auc_score"] = roc_auc_score(
                y_true=full_setup.test_data.labels,
                y_score=class_probabilities,
                average="weighted",
                multi_class="ovr",
            )
            print(
                f"""\nThe multi-class weighted ROC AUC score is: {result_dict["roc_auc_score"]}"""
            )

            self.plot_multiclass_roc(
                labels=full_setup.test_data.labels,
                class_probabilities=class_probabilities,
            )

        return result_dict

    def plot_multiclass_roc(
        self,
        labels: Iterable,
        class_probabilities: np.ndarray,
        fig_size: Tuple[int, int] = (8, 8),
    ) -> None:
        """Following from here: https://stackoverflow.com/questions/45332410/roc-for-multiclass-classification"""

        _, class_count = class_probabilities.shape

        fpr, tpr, roc_auc = {}, {}, {}

        # First, calculate all of the explicit class roc curves...
        y_test_dummies = pd.get_dummies(labels, drop_first=False).values
        for i in range(class_count):
            fpr[i], tpr[i], _ = roc_curve(
                y_test_dummies[:, i], class_probabilities[:, i]
            )
            roc_auc[i] = auc(fpr[i], tpr[i])

        #  Construct all plots
        fig, ax = plt.subplots(figsize=fig_size)
        ax.plot([0, 1], [0, 1], "k--")
        ax.set_xlim([0.0, 1.0])
        ax.set_ylim([0.0, 1.05])
        ax.set_xlabel("False Positive Rate")
        ax.set_ylabel("True Positive Rate")
        ax.set_title("Receiver operating characteristic evaluation")
        for i in range(class_count):
            ax.plot(
                fpr[i],
                tpr[i],
                label=f"ROC curve (area = {round(roc_auc[i], 2)}) for label {i}",
                alpha=0.6,
            )

        ax.legend(loc="best")
        ax.grid(alpha=0.4)
        sns.despine()
        plt.show()


class RegressionExperimentBase(ExperimentBase):
    def __init__(
        self,
        train_setup: MLSetup,
        test_setup: MLSetup,
        cv_split_count: int = 5,
        rnd_int: int = 100,
        model_dir: Optional[Union[str, Path]] = None,
        model_storage_function: Optional[Callable] = None,
        model_loading_function: Optional[Callable] = None,
        model_tag: str = "_development",
        process_tag: str = "_development",
    ) -> None:
        super().__init__(
            train_setup,
            test_setup,
            cv_split_count,
            rnd_int,
            model_dir,
            model_storage_function,
            model_loading_function,
            model_tag,
            process_tag,
        )
        self.baseline_value = None
        self.standard_metric = "neg_root_mean_squared_error"
        self.metric_dict = {
            "mse": mean_squared_error,
            "mae": mean_absolute_error,
        }

    def evaluate_predictions(
        self,
        labels: Iterable,
        predictions: Iterable,
        class_probabilities: Optional[Iterable] = None,
        baseline_prediction: bool = False,
    ) -> Dict[str, float]:
        """Evaluate all predictions, and return the results in a dict"""

        if baseline_prediction:
            if not self.baseline_value:
                raise ValueError(
                    "No baseline value was provided to the class and a baseline evaluation was called. Either set a baseline value or pass baseline_prediction=False to evaluate_predictions method."
                )
            evaluation_prediction = self.baseline_value
        else:
            evaluation_prediction = predictions

        result_dict: Dict[str, float] = {}
        # First test the predictions in the metric dictionary...
        for name, metric in self.metric_dict.items():
            result_dict[name] = metric(labels, evaluation_prediction)
            print(f"\nThe {name} is: {result_dict[name]}")
        return result_dict
