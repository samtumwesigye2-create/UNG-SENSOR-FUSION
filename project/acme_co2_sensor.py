"""Example plugin - a vendor CO2 sensor, following the read-only Sensor contract."""
import random
from sensor_fusion import Sensor
from plugin_loader import register_sensor


@register_sensor("acme_co2")
class AcmeCO2Sensor(Sensor):
    def __init__(self, sensor_id, bus, interval=5.0):
        super().__init__(sensor_id, "co2_ppm", bus, interval=interval)

    def read_raw(self):
        return round(400 + random.uniform(-20, 20), 1)
