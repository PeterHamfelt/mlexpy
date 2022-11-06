import pandas as pd
from pathlib import Path
from typing import Union, Callable, Optional
from mlexpy import processor, experiment, pipeline_utils


class IrisPipeline(processor.ProcessPipelineBase):
    def __init__(
        self,
        process_tag: str = "example_development_process",
        model_dir: Optional[Union[str, Path]] = None,
        model_storage_function: Optional[Callable] = None,
        model_loading_function: Optional[Callable] = None,
    ) -> None:
        super().__init__(
            process_tag, model_dir, model_storage_function, model_loading_function
        )

    # Now -- define the .process_data() method.
    def process_data(self, df: pd.DataFrame, training: bool = True) -> pd.DataFrame:
        """All data prrocessing that is to be performed for the iris classification task."""

        # Do a copy of the passed df
        df = df.copy()

        # First, compute the petal / sepal areas (but make the columns simpler)
        df.columns = [col.replace(" ", "_").strip("_(cm)") for col in df.columns]

        for object in ["petal", "sepal"]:
            df[f"{object}_area"] = df[f"{object}_length"] * df[f"{object}_width"]

        # Now perform the training / testing dependent feature processsing. This is why a `training` boolean is passed.

        if training:
            # Now FIT all of the model based features...
            self.fit_model_based_features(df)
            # ... and get the results of a transformation of all model based features.
            model_features = self.transform_model_based_features(df)
        else:
            # Here we can ONLY apply the transformation
            model_features = self.transform_model_based_features(df)

        # Now, add these 2 dataframes toghert "horizontaly"

        all_feature_df = pd.concat([df, model_features], axis=1)

        # Imagine we only want to use the scaled features for prediction, then we retrieve only the scaled colums.
        # (This is easy becuase the columns are renamed with the model name in the column name)

        prediction_df = all_feature_df[
            [col for col in all_feature_df if "standardscaler" in col]
        ]

        return prediction_df

    def fit_model_based_features(self, df: pd.DataFrame) -> None:
        """
        Here we do any processing of columns that will require a model based transformation / engineering.

        In this case, simply fit a standard (normalization) scaler to the numerical columns.
        This case will result in additional columns on the dataframe named as
        "<original-column-name>_StandardScaler()".

        Note: there are no returned values for this method, the reult is an update in the self.column_transformations dictionary
        """
        for column in df.columns:
            if df[column].dtype not in ("float", "int"):
                continue
            self.fit_scaler(df[column], standard_scaling=True)


class IrisExpirament(experiment.ClassifierExpirament):
    def __init__(
        self,
        train_setup: pipeline_utils.MLSetup,
        test_setup: pipeline_utils.MLSetup,
        cv_split_count: int,
        rnd_int: int = 100,
        model_dir: Optional[Union[str, Path]] = None,
        model_storage_function: Optional[Callable] = None,
        model_loading_function: Optional[Callable] = None,
        model_tag: str = "example_development_model",
        process_tag: str = "example_development_process",
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

    def process_data(
        self,
    ) -> pipeline_utils.ExperimentSetup:

        processor = IrisPipeline(process_tag=self.process_tag, model_dir=self.model_dir)

        # Now call the .process_data() method we defined above.
        train_df = processor.process_data(self.training.obs, training=True)
        test_df = processor.process_data(self.testing.obs, training=False)

        print(
            f"The train data are of size {train_df.shape}, the test data are {test_df.shape}."
        )

        assert (
            len(set(train_df.index).intersection(set(test_df.index))) == 0
        ), "There are duplicated indecies in the train and test set."

        return pipeline_utils.ExperimentSetup(
            pipeline_utils.MLSetup(
                train_df,
                self.training.labels,
            ),
            pipeline_utils.MLSetup(
                test_df,
                self.testing.labels,
            ),
        )
