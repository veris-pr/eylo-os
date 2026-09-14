"""Typeform native form, submission and tagged-answer contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Annotated, Literal, NoReturn, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from ...contracts import VendorResponse, VendorToolError

MAX_TEXT_CHARS = 4_000
DEFAULT_PAGE_SIZE = 25
MAX_FORM_PAGE_SIZE = 200
MAX_RESPONSE_PAGE_SIZE = 100
MAX_CURSOR_CHARS = 1_024
UNSUBMITTED_TIMESTAMP = "0001-01-01T00:00:00Z"


class TypeformErrorCode(StrEnum):
    RESPONSE_INVALID = "vendor_response_invalid"
    REJECTED = "vendor_rejected"


class ResponseType(StrEnum):
    STARTED = "started"
    PARTIAL = "partial"
    COMPLETED = "completed"


class FieldType(StrEnum):
    CALENDLY = "calendly"
    CHECKBOX = "checkbox"
    CONTACT_INFO = "contact_info"
    DATE = "date"
    DROPDOWN = "dropdown"
    EMAIL = "email"
    FILE_UPLOAD = "file_upload"
    GOOGLE_CALENDAR = "google_calendar"
    GROUP = "group"
    LEGAL = "legal"
    LONG_TEXT = "long_text"
    MATRIX = "matrix"
    MULTI_FORMAT = "multi_format"
    MULTIPLE_CHOICE = "multiple_choice"
    NPS = "nps"
    NUMBER = "number"
    OPINION_SCALE = "opinion_scale"
    PAYMENT = "payment"
    PHONE_NUMBER = "phone_number"
    PICTURE_CHOICE = "picture_choice"
    RANKING = "ranking"
    RATING = "rating"
    SHORT_TEXT = "short_text"
    SIGNATURE = "signature"
    STATEMENT = "statement"
    WEBSITE = "website"
    YES_NO = "yes_no"


class AnswerType(StrEnum):
    TEXT = "text"
    EMAIL = "email"
    URL = "url"
    FILE_URL = "file_url"
    PHONE_NUMBER = "phone_number"
    DATE = "date"
    NUMBER = "number"
    BOOLEAN = "boolean"
    CHOICE = "choice"
    CHOICES = "choices"
    PAYMENT = "payment"
    MULTI_FORMAT = "multi_format"
    SIGNATURE = "signature"


class SignatureType(StrEnum):
    TYPED = "typed"
    DRAWN = "drawn"
    UPLOADED = "uploaded"


def timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if "T" not in value or parsed.tzinfo is None:
        raise ValueError("Typeform timestamps require an explicit timezone.")
    return value


Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+$", min_length=1)]
Cursor = Annotated[
    str, Field(pattern=r"^[^\s\x00-\x1f\x7f]+$", max_length=MAX_CURSOR_CHARS)
]
Timestamp = Annotated[str, AfterValidator(timestamp)]
NativeFieldType = Annotated[
    FieldType,
    BeforeValidator(
        lambda value: FieldType(value) if isinstance(value, str) else value
    ),
]
NativeResponseType = Annotated[
    ResponseType,
    BeforeValidator(
        lambda value: ResponseType(value) if isinstance(value, str) else value
    ),
]
NativeSignatureType = Annotated[
    SignatureType,
    BeforeValidator(
        lambda value: SignatureType(value) if isinstance(value, str) else value
    ),
]


class TypeformModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="ignore",
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


class TypeformRequest(TypeformModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Links(TypeformModel):
    display: str | None = None


class FormSummary(TypeformModel):
    id: Identifier
    title: str
    links: Links = Field(alias="_links")
    last_updated_at: Timestamp


class FormsPage(TypeformModel):
    total_items: int = Field(ge=0)
    page_count: int = Field(ge=0)
    items: list[FormSummary]


class Choice(TypeformModel):
    label: str


class Validations(TypeformModel):
    required: bool = False


class FieldProperties(TypeformModel):
    choices: list[Choice] = Field(default_factory=list)
    fields: list[FormField] = Field(default_factory=list)


class FormField(TypeformModel):
    id: Identifier
    title: str
    type: NativeFieldType
    validations: Validations = Field(default_factory=Validations)
    properties: FieldProperties = Field(default_factory=FieldProperties)


class Form(TypeformModel):
    id: Identifier
    title: str
    links: Links = Field(default_factory=Links, alias="_links")
    fields: list[FormField]


class AnswerField(TypeformModel):
    id: Identifier
    type: NativeFieldType
    ref: str | None = None


class AnswerBase(TypeformModel):
    field: AnswerField


class TextAnswer(AnswerBase):
    type: Literal[AnswerType.TEXT]
    text: str = Field(repr=False)


class EmailAnswer(AnswerBase):
    type: Literal[AnswerType.EMAIL]
    email: str = Field(repr=False)


class UrlAnswer(AnswerBase):
    type: Literal[AnswerType.URL]
    url: str = Field(repr=False)


class FileAnswer(AnswerBase):
    type: Literal[AnswerType.FILE_URL]
    file_url: str = Field(repr=False)


class PhoneAnswer(AnswerBase):
    type: Literal[AnswerType.PHONE_NUMBER]
    phone_number: str = Field(repr=False)


class DateAnswer(AnswerBase):
    type: Literal[AnswerType.DATE]
    date: str = Field(repr=False)


class NumberAnswer(AnswerBase):
    type: Literal[AnswerType.NUMBER]
    number: int | float


class BooleanAnswer(AnswerBase):
    type: Literal[AnswerType.BOOLEAN]
    boolean: bool


class SelectedChoice(TypeformModel):
    label: str | None = None
    other: str | None = None

    @model_validator(mode="after")
    def has_value(self) -> Self:
        if self.label is None and self.other is None:
            raise ValueError("A selected choice needs its label or other text.")
        return self


class SelectedChoices(TypeformModel):
    labels: list[str] | None = None
    other: str | None = None

    @model_validator(mode="after")
    def has_value(self) -> Self:
        if self.labels is None and self.other is None:
            raise ValueError("A choices answer needs labels or other text.")
        return self


class ChoiceAnswer(AnswerBase):
    type: Literal[AnswerType.CHOICE]
    choice: SelectedChoice


class ChoicesAnswer(AnswerBase):
    type: Literal[AnswerType.CHOICES]
    choices: SelectedChoices


class Payment(TypeformModel):
    amount: str | None = None
    last4: str | None = Field(default=None, repr=False)
    name: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def has_value(self) -> Self:
        if self.amount is None and self.last4 is None and self.name is None:
            raise ValueError("Payment answer has no documented value.")
        return self


class PaymentAnswer(AnswerBase):
    type: Literal[AnswerType.PAYMENT]
    payment: Payment


class MultiFormat(TypeformModel):
    audio_url: str | None = None
    audio_transcript: str | None = Field(default=None, repr=False)
    video_url: str | None = None
    video_transcript: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def has_media(self) -> Self:
        if not self.audio_url and not self.video_url:
            raise ValueError("A media answer must identify audio or video.")
        return self


class MultiFormatAnswer(AnswerBase):
    type: Literal[AnswerType.MULTI_FORMAT]
    multi_format: MultiFormat


class Signature(TypeformModel):
    url: str
    type: NativeSignatureType


class SignatureAnswer(AnswerBase):
    type: Literal[AnswerType.SIGNATURE]
    signature: Signature


Answer = Annotated[
    TextAnswer
    | EmailAnswer
    | UrlAnswer
    | FileAnswer
    | PhoneAnswer
    | DateAnswer
    | NumberAnswer
    | BooleanAnswer
    | ChoiceAnswer
    | ChoicesAnswer
    | PaymentAnswer
    | MultiFormatAnswer
    | SignatureAnswer,
    Field(discriminator="type"),
]


class ResponseMetadata(TypeformModel):
    browser: str | None = None
    platform: str | None = None


class Submission(TypeformModel):
    response_id: str | None = None
    token: Cursor
    response_type: NativeResponseType | None = None
    submitted_at: Timestamp | None = None
    landed_at: Timestamp
    staged_at: Timestamp | None = None
    answers: list[Answer] | None = Field(default=None, repr=False)
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)
    hidden: dict[str, str] = Field(default_factory=dict, repr=False)


class ResponsesPage(TypeformModel):
    total_items: int = Field(ge=0)
    page_count: int = Field(ge=0)
    items: list[Submission]


class FormsQuery(TypeformRequest):
    page_size: int = Field(ge=1, le=MAX_FORM_PAGE_SIZE)
    page: int = Field(ge=1)
    search: str | None = None


class ResponsesQuery(TypeformRequest):
    page_size: int = Field(ge=1, le=MAX_RESPONSE_PAGE_SIZE)
    response_type: ResponseType
    since: str | None = None
    before: Cursor | None = None


class FormView(TypeformModel):
    id: str
    title: str
    public_link: str | None
    last_updated: str


class FormsView(TypeformModel):
    forms: list[FormView]
    count: int
    total: int
    next_page: int | None


class QuestionView(TypeformModel):
    id: str
    question: str
    type: FieldType
    required: bool
    choices: list[str] | None
    parent_id: str | None


class FormViewDetails(TypeformModel):
    id: str
    title: str
    public_link: str | None
    questions: list[QuestionView]
    question_count: int


class AnswerView(TypeformModel):
    field_id: str
    question: str
    answer: str | int | float | bool | list[str] | Payment | MultiFormat | Signature
    type: AnswerType


class SubmissionView(TypeformModel):
    response_id: str | None
    response_token: str
    submitted_at: str | None
    response_type: ResponseType
    completed: bool
    answers: list[AnswerView]
    metadata: ResponseMetadata
    hidden_fields: dict[str, str]


class ResponsesView(TypeformModel):
    form_id: str
    form_title: str
    responses: list[SubmissionView]
    count: int
    total: int
    next_before: str | None


FORMS_RESPONSE = TypeAdapter(FormsPage)
FORM_RESPONSE = TypeAdapter(Form)
RESPONSES_RESPONSE = TypeAdapter(ResponsesPage)


def invalid_response() -> NoReturn:
    raise VendorToolError(
        TypeformErrorCode.RESPONSE_INVALID,
        "Typeform returned an invalid response for the requested operation.",
    )


def parse_response[T](response: VendorResponse, schema: TypeAdapter[T]) -> T:
    if not response.ok:
        raise VendorToolError(
            TypeformErrorCode.REJECTED, "Typeform rejected the request."
        )
    if response.status_code != HTTPStatus.OK:
        invalid_response()
    try:
        return schema.validate_python(response.data, strict=True)
    except ValidationError:
        invalid_response()
