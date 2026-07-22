from pydantic import BaseModel

from withings_client import MeasureType

class Measurement(BaseModel):
    weight: float
    muscle_mass: float
    bone_mass: float
    visceral_fat: float
    fat_ratio: float

    @classmethod
    def from_json(cls, measures):
        return cls(**{MeasureType(m['type']).name.lower(): m['value']*10**m['unit'] for m in measures})