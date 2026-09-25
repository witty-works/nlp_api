"""Context checker using SetFit models for local inference."""

import os
import logging

from app.models import LangType
from app.settings import Settings


class ContextChecker:
    """Manages SetFit models for context-aware false positive detection."""

    def __init__(self, settings: Settings, logger: logging.Logger):
        self.settings = settings
        self.logger = logger
        self.models = {}

        if not settings.context_checker_local:
            return

        # Only import SetFit if local models are enabled
        try:
            from setfit import SetFitModel

            self._load_models(SetFitModel)
        except ImportError:
            self.logger.warning(
                "SetFit not installed. Context checker local models disabled."
            )

    def _load_models(self, SetFitModel):
        """Load SetFit models for available languages."""
        base_path = os.path.join(os.getcwd(), "models", "context_aware_model")

        # Map language codes to model paths
        lang_paths = {
            LangType.EN: f"{base_path}/en",
            LangType.DE: f"{base_path}/de",
            LangType.FR: f"{base_path}/fr",
        }

        for lang, model_path in lang_paths.items():
            # Check for either SafeTensors (preferred) or PyTorch format
            has_safetensors = os.path.isfile(f"{model_path}/model.safetensors")
            has_pytorch = os.path.isfile(f"{model_path}/pytorch_model.bin")

            if has_safetensors or has_pytorch:
                try:
                    self.logger.info(
                        f"Loading SetFit model for {lang} from {model_path}"
                    )
                    # Force CPU device to enable shared memory across processes
                    model = SetFitModel.from_pretrained(model_path, device="cpu")
                    # Enable shared memory for multi-process use
                    model.model_body.share_memory()
                    # Set to evaluation mode
                    model.model_body.eval()
                    self.models[lang] = model
                    self.logger.info(f"Successfully loaded SetFit model for {lang}")
                except Exception as e:
                    self.logger.error(f"Failed to load SetFit model for {lang}: {e}")

    def predict(self, lang: LangType, sentences: list[str]) -> list[bool]:
        """
        Predict whether sentences contain genuine issues (True) or false positives (False).

        Args:
            lang: Language code
            sentences: List of sentences to check

        Returns:
            List of boolean predictions (True = genuine issue, False = false positive)
        """
        if lang not in self.models:
            # If model not available, assume all are genuine issues
            return [True] * len(sentences)

        try:
            # Get predictions from model
            predictions = self.models[lang](sentences)
            # Convert to list of booleans
            return [bool(pred.item()) for pred in predictions]
        except Exception as e:
            self.logger.error(f"Error during SetFit prediction for {lang}: {e}")
            # On error, assume all are genuine issues
            return [True] * len(sentences)

    def is_available(self, lang: LangType) -> bool:
        """Check if a model is available for the given language."""
        return lang in self.models
