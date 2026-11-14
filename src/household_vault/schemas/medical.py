from pydantic import BaseModel

from household_vault.schemas._coerce import FlexDate, Name, Text


class Medicine(BaseModel):
    name: Text | None = None
    dose: Text | None = None
    timing: Text | None = None
    duration: Text | None = None

    def key(self) -> str:
        """Item text in the ground truth's shape: 'Cetirizine 10 mg 1-1-1 5 days'."""
        return " ".join(p for p in (self.name, self.dose, self.timing, self.duration) if p)


class LabTest(BaseModel):
    name: Text | None = None
    value: Text | None = None
    unit: Text | None = None

    def key(self) -> str:
        """Canonical item text, the same shape as the ground truth: 'HbA1c=4.2 %'."""
        return f"{self.name or ''}={self.value or ''} {self.unit or ''}".strip()


class Prescription(BaseModel):
    hospital: Text | None = None
    doctor: Name | None = None
    patient: Name | None = None
    date: FlexDate | None = None
    medicines: list[Medicine] | None = None
    next_visit: FlexDate | None = None


class LabReport(BaseModel):
    lab: Text | None = None
    patient: Name | None = None
    date: FlexDate | None = None
    tests: list[LabTest] | None = None
