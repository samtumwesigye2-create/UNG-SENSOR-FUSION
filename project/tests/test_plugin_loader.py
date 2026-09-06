import sys
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin_loader import PluginLoader, SENSOR_REGISTRY


def test_plugin_loader_registers_and_reports_hash(tmp_path):
    fake_sensor_fusion = types.ModuleType("sensor_fusion")
    fake_sensor_fusion.Sensor = type("Sensor", (), {})
    sys.modules["sensor_fusion"] = fake_sensor_fusion
    plugin = tmp_path / "co2.py"
    plugin.write_text(
        "from plugin_loader import register_sensor\n"
        "from sensor_fusion import Sensor\n"
        "@register_sensor('test_co2')\n"
        "class TestCO2(Sensor):\n"
        "    pass\n"
    )
    loader = PluginLoader(str(tmp_path))
    loader.discover()
    assert "test_co2" in SENSOR_REGISTRY
    assert len(loader.loaded) == 1
    assert len(loader.loaded[0]["sha256"]) == 64


def test_broken_plugin_does_not_abort_discovery(tmp_path):
    (tmp_path / "a_broken.py").write_text("raise RuntimeError('boom')\n")
    (tmp_path / "b_good.py").write_text("VALUE = 1\n")
    loader = PluginLoader(str(tmp_path))
    loader.discover()
    assert len(loader.failed) == 1
    assert len(loader.loaded) == 1
