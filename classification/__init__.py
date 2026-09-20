from .base import Classification, Classifier, EventFeatures
from .rules import EventRuleClassifier

default_classifier: Classifier = EventRuleClassifier()

__all__ = [
    "Classification",
    "Classifier",
    "EventFeatures",
    "EventRuleClassifier",
    "default_classifier",
]
