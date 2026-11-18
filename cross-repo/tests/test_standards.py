from types import SimpleNamespace

from core import standards
from core.service_chain_resolver import resolve_class_kind


def test_yaml_classification_patterns_are_consumed(tmp_path, monkeypatch):
    (tmp_path / 'spring-boot.yml').write_text(
        'layering:\n  layers:\n    - name: Controller\n'
        '      annotations: ["@WebEntry"]\n      naming_pattern: "*Boundary.java"\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(standards, 'get_settings', lambda: SimpleNamespace(standards_dir=str(tmp_path)))
    assert resolve_class_kind('@WebEntry class Foo {}', 'Foo', 'java') == 'controller'
    assert resolve_class_kind('class FooBoundary {}', 'FooBoundary', 'java') == 'controller'


def test_missing_standards_keep_builtin_classification(tmp_path, monkeypatch):
    monkeypatch.setattr(standards, 'get_settings', lambda: SimpleNamespace(standards_dir=str(tmp_path)))
    assert resolve_class_kind('@Service class Foo {}', 'Foo', 'java') == 'service'
