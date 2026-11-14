from pydantic import BaseModel, Field

from household_vault.schemas._coerce import (
    Amount,
    FlexDate,
    Identifier,
    Name,
    NameItem,
    Text,
)


class Policy(BaseModel):
    insurer: Text | None = None
    product: Text | None = None
    policy_number: Identifier | None = None
    policyholder: Name | None = None
    insured: list[NameItem] | None = None
    nominee: Name | None = None
    sum_insured: Amount | None = None
    premium: Amount | None = None
    premium_frequency: Text | None = None
    start_date: FlexDate | None = None
    end_date: FlexDate | None = None
    premium_due_date: FlexDate | None = None
    agent: Text | None = Field(default=None, description="agent or third-party administrator")
    claim_helpline: Identifier | None = None


class HealthPolicy(Policy):
    pass


class VehiclePolicy(Policy):
    registration_number: Identifier | None = None
    idv: Amount | None = None
    ncb_percent: Amount | None = None
