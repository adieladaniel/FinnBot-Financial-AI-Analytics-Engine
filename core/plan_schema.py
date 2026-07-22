from typing import Literal, Optional
from pydantic import BaseModel, Field


class PlanFilter(BaseModel):
    column: str = Field(description="Dataset column this filter applies to.")
    operator: Literal["eq", "gt", "lt", "gte", "lte", "in", "date_between"] = Field(
        description="Comparison operator for the filter."
    )
    values: list[str] = Field(
        default_factory=list,
        description=(
            "Values to compare against. Numeric comparisons still use strings here "
            "(e.g. '50000'); 'date_between' takes exactly two ISO date strings."
        ),
    )


class LLMPlan(BaseModel):
    task: Literal[
        "grouped_table",
        "grouped_table_multi",
        "single_value",
        "single_value_multi",
        "count",
        "count_extreme",
        "raw_table",
    ] = Field(description="The kind of analysis to run.")
    group_by: list[str] = Field(
        default_factory=list,
        description="Dimension column(s) to group by. Empty for single_value/count without grouping.",
    )
    measure: Optional[str] = Field(
        default=None,
        description="Single measure name to use, for single-measure tasks.",
    )
    measures: Optional[list[str]] = Field(
        default=None,
        description="Multiple measure names, only for *_multi tasks (comparisons).",
    )
    sort_order: Literal["asc", "desc"] = Field(
        default="desc",
        description="Sort direction for ranking/grouped results.",
    )
    limit: int = Field(default=10, description="Max number of rows to return.")
    filters: list[PlanFilter] = Field(
        default_factory=list,
        description="Filters to apply before aggregation.",
    )
