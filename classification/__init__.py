from .base import Classification, Classifier, SiteFeatures
from .rules import RuleClassifier

default_classifier: Classifier = RuleClassifier()

__all__ = ["Classification", "Classifier", "SiteFeatures", "RuleClassifier", "default_classifier"]
