from withings_client import MeasureType


def decimal_places(value: int, unit: int) -> int:
    if unit >= 0:
        return 0

    decimals = -unit
    abs_value = abs(value)
    removable = 0

    while removable < decimals and abs_value != 0 and abs_value % 10 == 0:
        abs_value //= 10
        removable += 1

    return decimals - removable


def get_measurements(client, *meastypes):
    json = client.get_measurements(meastypes=meastypes, category=1)
    measurements = json['body']['measuregrps']

    thing = {'timestamp': [], **{t.name.lower(): [] for t in meastypes}}

    for i in measurements:
        thing['timestamp'].append(i['created'])
        for m in i['measures']:
            key = MeasureType(m['type']).name.lower()
            value = int(m['value'])
            unit = int(m['unit'])
            decimals = decimal_places(value, unit)
            scaled = value * (10 ** unit)
            rounded = round(scaled, decimals)
            thing[key].append(rounded)

    return thing


def get_all_measurements(client):
    return {
        'height': get_measurements(client, MeasureType.HEIGHT),
        'heart': get_measurements(client, MeasureType.HEART_PULSE),
        'weight': get_measurements(
            client,
            MeasureType.BASAL_METABOLIC_RATE,
            MeasureType.BONE_MASS,
            MeasureType.FAT_FREE_MASS,
            MeasureType.FAT_MASS_WEIGHT,
            MeasureType.FAT_RATIO,
            MeasureType.HYDRATION,
            MeasureType.METABOLIC_AGE,
            MeasureType.METABOLIC_AGE,
            MeasureType.MUSCLE_MASS,
            MeasureType.WEIGHT,
        ),
    }

