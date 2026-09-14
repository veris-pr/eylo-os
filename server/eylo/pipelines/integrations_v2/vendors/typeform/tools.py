"""Read Typeform pages and join tagged submission answers to nested questions."""

from datetime import UTC, datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    model_validator,
)

from ...contracts import VendorToolContext
from ...registry import curated_tool
from .definition import FORMS_READ, RESPONSES_READ, vendor
from .schemas import (
    DEFAULT_PAGE_SIZE,
    FORMS_RESPONSE,
    FORM_RESPONSE,
    MAX_FORM_PAGE_SIZE,
    MAX_RESPONSE_PAGE_SIZE,
    MAX_TEXT_CHARS,
    RESPONSES_RESPONSE,
    UNSUBMITTED_TIMESTAMP,
    Answer,
    AnswerView,
    BooleanAnswer,
    ChoiceAnswer,
    ChoicesAnswer,
    Cursor,
    DateAnswer,
    EmailAnswer,
    FileAnswer,
    Form,
    FormField,
    FormView,
    FormViewDetails,
    FormsQuery,
    FormsView,
    Identifier,
    MultiFormat,
    MultiFormatAnswer,
    NumberAnswer,
    Payment,
    PaymentAnswer,
    PhoneAnswer,
    QuestionView,
    ResponseType,
    ResponsesQuery,
    ResponsesView,
    Signature,
    SignatureAnswer,
    Submission,
    SubmissionView,
    TextAnswer,
    UrlAnswer,
    invalid_response,
    parse_response,
)


class ListFormsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search: str | None = Field(default=None, description="Match forms by title.")
    limit: StrictInt = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_FORM_PAGE_SIZE)
    page: StrictInt = Field(default=1, ge=1, description="Use next_page to continue.")


class GetFormInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    form_id: Identifier = Field(description="Form ID, not its full URL.")


class ListResponsesInput(GetFormInput):
    response_type: ResponseType | None = Field(
        default=None,
        description="Choose completed, partial, or started. Omitted means completed.",
    )
    completed_only: StrictBool | None = Field(
        default=None,
        deprecated=True,
        description="Legacy input: true selects completed, false selects started. Use response_type instead.",
    )
    since: str | None = Field(
        default=None, description="ISO 8601 UTC or timezone-offset timestamp."
    )
    limit: StrictInt = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_RESPONSE_PAGE_SIZE)
    before: Cursor | None = Field(
        default=None,
        description="Use next_before unchanged to retrieve older responses.",
    )

    @model_validator(mode="after")
    def validate_selection(self) -> "ListResponsesInput":
        if self.response_type is not None and self.completed_only is not None:
            raise ValueError("Use response_type or completed_only, not both.")
        if self.since is not None:
            _since(self.since)
        return self

    @property
    def selected_type(self) -> ResponseType:
        if self.response_type is not None:
            return self.response_type
        return (
            ResponseType.STARTED
            if self.completed_only is False
            else ResponseType.COMPLETED
        )


def _since(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value:
        raise ValueError("since must include a date and time.")
    # Typeform documents timezone-less timestamps as UTC.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@curated_tool(
    vendor=vendor.vendor,
    name="list_forms",
    display_name="List Typeforms",
    description="List account forms with titles, IDs and public links. Continue using next_page with the same search and limit.",
    input_model=ListFormsInput,
    scopes=(FORMS_READ,),
)
async def list_forms(
    payload: ListFormsInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    query = FormsQuery(
        page_size=payload.limit, page=payload.page, search=payload.search
    )
    page = parse_response(
        await ctx.read(
            "/forms", query=query.model_dump(mode="json", exclude_none=True)
        ),
        FORMS_RESPONSE,
    )
    if len(page.items) > payload.limit or len(page.items) > page.total_items:
        invalid_response()
    if len({item.id for item in page.items}) != len(page.items):
        invalid_response()
    next_page = payload.page + 1 if payload.page < page.page_count else None
    if next_page is not None and not page.items:
        invalid_response()
    return FormsView(
        forms=[
            FormView(
                id=item.id,
                title=item.title,
                public_link=item.links.display,
                last_updated=item.last_updated_at,
            )
            for item in page.items
        ],
        count=len(page.items),
        total=page.total_items,
        next_page=next_page,
    ).model_dump(mode="json")


async def _form(form_id: str, ctx: VendorToolContext) -> Form:
    form = parse_response(await ctx.read(f"/forms/{form_id}"), FORM_RESPONSE)
    if form.id != form_id:
        invalid_response()
    return form


def _questions(fields: list[FormField]) -> list[QuestionView]:
    questions: list[QuestionView] = []
    seen: set[str] = set()
    stack: list[tuple[FormField, str | None]] = [
        (field, None) for field in reversed(fields)
    ]
    while stack:
        field, parent_id = stack.pop()
        if field.id in seen:
            invalid_response()
        seen.add(field.id)
        questions.append(
            QuestionView(
                id=field.id,
                question=field.title,
                type=field.type,
                required=field.validations.required,
                choices=[choice.label for choice in field.properties.choices] or None,
                parent_id=parent_id,
            )
        )
        stack.extend((child, field.id) for child in reversed(field.properties.fields))
    return questions


@curated_tool(
    vendor=vendor.vendor,
    name="get_form",
    display_name="Get Typeform Questions",
    description="Read a form's questions in order, including nested fields, choices and required flags. parent_id identifies grouped questions.",
    input_model=GetFormInput,
    scopes=(FORMS_READ,),
)
async def get_form(
    payload: GetFormInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    form = await _form(payload.form_id, ctx)
    questions = _questions(form.fields)
    return FormViewDetails(
        id=form.id,
        title=form.title,
        public_link=form.links.display,
        questions=questions,
        question_count=len(questions),
    ).model_dump(mode="json")


@curated_tool(
    vendor=vendor.vendor,
    name="list_responses",
    display_name="List Typeform Responses",
    description=(
        "Read submissions as question-and-answer pairs joined by field ID, including nested questions. "
        "Select completed, partial, or started responses. Continue with next_before and unchanged filters. "
        "Recent submissions may not yet be available through Typeform's Responses API. File/media URLs are references, not downloaded contents."
    ),
    input_model=ListResponsesInput,
    scopes=(RESPONSES_READ, FORMS_READ),
)
async def list_responses(
    payload: ListResponsesInput, ctx: VendorToolContext
) -> dict[str, JsonValue]:
    form = await _form(payload.form_id, ctx)
    questions = {question.id: question.question for question in _questions(form.fields)}
    query = ResponsesQuery(
        page_size=payload.limit,
        response_type=payload.selected_type,
        since=_since(payload.since) if payload.since is not None else None,
        before=payload.before,
    )
    page = parse_response(
        await ctx.read(
            f"/forms/{form.id}/responses",
            query=query.model_dump(mode="json", exclude_none=True),
        ),
        RESPONSES_RESPONSE,
    )
    if len(page.items) > payload.limit or len(page.items) > page.total_items:
        invalid_response()
    tokens = [item.token for item in page.items]
    if len(set(tokens)) != len(tokens) or payload.before in tokens:
        invalid_response()
    if page.page_count > 1 and not page.items:
        invalid_response()
    # Token pagination is exclusive. A full page can require a final empty request;
    # never infer collection exhaustion from a potentially capped total.
    next_before = (
        page.items[-1].token
        if page.items and (len(page.items) == payload.limit or page.page_count > 1)
        else None
    )
    return ResponsesView(
        form_id=form.id,
        form_title=form.title,
        responses=[
            _submission(item, questions, payload.selected_type) for item in page.items
        ],
        count=len(page.items),
        total=page.total_items,
        next_before=next_before,
    ).model_dump(mode="json")


def _submission(
    item: Submission, questions: dict[str, str], selected_type: ResponseType
) -> SubmissionView:
    if item.response_type is not None and item.response_type != selected_type:
        invalid_response()
    submitted_at = (
        None if item.submitted_at == UNSUBMITTED_TIMESTAMP else item.submitted_at
    )
    if selected_type == ResponseType.COMPLETED and (
        submitted_at is None or item.answers is None
    ):
        invalid_response()
    return SubmissionView(
        response_id=item.response_id,
        response_token=item.token,
        submitted_at=submitted_at,
        response_type=selected_type,
        completed=selected_type == ResponseType.COMPLETED,
        answers=[
            AnswerView(
                field_id=answer.field.id,
                question=questions.get(answer.field.id, f"<field {answer.field.id}>"),
                answer=_value(answer),
                type=answer.type,
            )
            for answer in item.answers or []
        ],
        metadata=item.metadata,
        hidden_fields=item.hidden,
    )


def _value(
    answer: Answer,
) -> str | int | float | bool | list[str] | Payment | MultiFormat | Signature:
    match answer:
        case TextAnswer(text=value) | DateAnswer(date=value):
            return value[:MAX_TEXT_CHARS]
        case (
            EmailAnswer(email=value)
            | UrlAnswer(url=value)
            | FileAnswer(file_url=value)
            | PhoneAnswer(phone_number=value)
        ):
            return value
        case NumberAnswer(number=value):
            return value
        case BooleanAnswer(boolean=value):
            return value
        case ChoiceAnswer(choice=value):
            return value.other if value.other is not None else value.label or ""
        case ChoicesAnswer(choices=value):
            return [
                *(value.labels or []),
                *([value.other] if value.other is not None else []),
            ]
        case PaymentAnswer(payment=value):
            return value
        case MultiFormatAnswer(multi_format=value):
            return MultiFormat(
                audio_url=value.audio_url,
                video_url=value.video_url,
                audio_transcript=value.audio_transcript[:MAX_TEXT_CHARS]
                if value.audio_transcript is not None
                else None,
                video_transcript=value.video_transcript[:MAX_TEXT_CHARS]
                if value.video_transcript is not None
                else None,
            )
        case SignatureAnswer(signature=value):
            return value
    invalid_response()


__all__ = ["get_form", "list_forms", "list_responses"]
