"""Read classification patterns from the repository's YAML standards."""
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
import re

import yaml

from config import get_settings


@lru_cache(maxsize=8)
def load_rules(directory: str) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
    root = Path(directory)
    rules = []
    spring = root / 'spring-boot.yml'
    if spring.exists():
        data = yaml.safe_load(spring.read_text(encoding='utf-8')) or {}
        for layer in data.get('layering', {}).get('layers', []):
            patterns = tuple(part.strip() for part in layer.get('naming_pattern', '').split(' or '))
            rules.append((layer['name'].lower(), tuple(layer.get('annotations', [])), patterns))
    angular = root / 'angular.yml'
    if angular.exists():
        data = yaml.safe_load(angular.read_text(encoding='utf-8')) or {}
        for entry in data.get('naming_conventions', {}).get('patterns', []):
            if entry.get('type') in {'Component', 'Service'} and entry.get('class_name'):
                pattern = re.sub(r'\{[^}]+\}', '*', entry['class_name'])
                rules.append((entry['type'].lower(), (), (pattern,)))
    return tuple(rules)


def classify(text: str, class_name: str, language: str) -> str | None:
    if language not in {'java', 'typescript', 'javascript'}:
        return None
    rules = load_rules(get_settings().standards_dir)
    filename = class_name + '.java' if language == 'java' else class_name
    for kind, annotations, patterns in rules:
        if language != 'java' and annotations:
            continue
        if any(re.search(re.escape(annotation) + r'\b', text) for annotation in annotations):
            return kind
        if any(fnmatchcase(filename, pattern) for pattern in patterns if pattern):
            return kind
    return None
