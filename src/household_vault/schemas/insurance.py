from pydantic import BaseModel

from household_vault.schemas._coerce import Amount, FlexDate, Text


class HealthPolicy(BaseModel):
    insurer: Text | None = None
    policy_number: Text | None = None
    policyholder: Text | None = None
    start_date: FlexDate | None = None
    end_date: FlexDate | None = None
    insured: list[str] | None = None
    nominee: Text | None = None
    sum_insured: Amount | None = None
    premium: Amount | None = None
    claim_helpline: Text | None = None


class VehiclePolicy(BaseModel):
    insurer: Text | None = None
    policy_number: Text | None = None
    policyholder: Text | None = None
    start_date: FlexDate | None = None
    end_date: FlexDate | None = None
    registration_number: Text | None = None
    idv: Amount | None = None
    ncb_percent: Amount | None = None
    premium: Amount | None = None
    claim_helpline: Text | None = None
