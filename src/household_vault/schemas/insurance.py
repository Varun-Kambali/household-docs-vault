from pydantic import BaseModel

from household_vault.schemas._coerce import Amount, FlexDate, Identifier, Name, Text


class HealthPolicy(BaseModel):
    insurer: Text | None = None
    policy_number: Identifier | None = None
    policyholder: Name | None = None
    start_date: FlexDate | None = None
    end_date: FlexDate | None = None
    insured: list[str] | None = None
    nominee: Name | None = None
    sum_insured: Amount | None = None
    premium: Amount | None = None
    claim_helpline: Identifier | None = None


class VehiclePolicy(BaseModel):
    insurer: Text | None = None
    policy_number: Identifier | None = None
    policyholder: Name | None = None
    start_date: FlexDate | None = None
    end_date: FlexDate | None = None
    registration_number: Identifier | None = None
    idv: Amount | None = None
    ncb_percent: Amount | None = None
    premium: Amount | None = None
    claim_helpline: Identifier | None = None
