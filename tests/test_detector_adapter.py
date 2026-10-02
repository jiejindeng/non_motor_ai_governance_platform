from detector import BicycleDetector


def test_label_aliases():
    assert BicycleDetector._standard_label("E-bike") == "electric_bicycle"
    assert BicycleDetector._standard_label("Electric Bike") == "electric_bicycle"
    assert BicycleDetector._standard_label("Bicycle") == "bicycle"
