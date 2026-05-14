from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.models.entities import (
    ApprovalStatus,
    AssessmentType,
    DocumentType,
    LessonType,
    ModerationStatus,
    ProviderType,
    QuestionType,
    UserRole,
)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole


class SignupRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=8, max_length=128)
    role: UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: UserRole

    model_config = {"from_attributes": True}


class RegisterRoleRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    role: UserRole
    student_age: int | None = Field(default=None, ge=1, le=120)
    verification_id_type: str | None = None
    verification_id_number: str | None = None
    verification_country_code: str | None = None
    verification_document_url: str | None = None


class AdminRecoveryRequest(BaseModel):
    recovery_key: str = Field(min_length=8, max_length=256)


class AdminSetUserPasswordRequest(BaseModel):
    email: EmailStr
    new_password: str = Field(min_length=8, max_length=128)
    recovery_key: str = Field(min_length=8, max_length=256)


class ProviderProfileCreate(BaseModel):
    provider_type: ProviderType
    display_name: str
    description: str = ""
    business_registration_type: str | None = None
    business_registration_number: str | None = None
    business_registration_country: str | None = None


class ProviderProfileOut(BaseModel):
    id: int
    user_id: int
    provider_type: ProviderType
    display_name: str
    description: str
    business_registration_type: str | None = None
    business_registration_number: str | None = None
    business_registration_country: str | None = None
    approval_status: ApprovalStatus
    rejection_reason: str | None

    model_config = {"from_attributes": True}


class ProviderDocumentCreate(BaseModel):
    document_type: DocumentType
    file_url: str


class ProviderDocumentOut(BaseModel):
    id: int
    provider_id: int
    document_type: DocumentType
    file_url: str
    status: ApprovalStatus
    review_note: str | None

    model_config = {"from_attributes": True}


class CourseCreate(BaseModel):
    title: str
    description: str
    category: str
    suitable_age_ranges: list[str] = Field(default_factory=list)
    thumbnail_url: str | None = None
    intro_video_url: str | None = None
    preview_video_url: str | None = None
    main_video_url: str | None = None
    includes_certification_exam: bool = False
    price_currency: str = Field(default="INR", min_length=3, max_length=8)
    base_price_amount: float = Field(default=0, ge=0)
    gst_rate: float = Field(default=0.18, ge=0)
    platform_commission_rate: float = Field(default=0.25, ge=0)
    hosting_fee_amount: float = Field(default=2500, ge=0)
    gst_amount: float = Field(default=0, ge=0)
    platform_commission_amount: float = Field(default=0, ge=0)
    final_price_amount: float = Field(default=0, ge=0)


class CourseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    suitable_age_ranges: list[str] | None = None
    thumbnail_url: str | None = None
    intro_video_url: str | None = None
    preview_video_url: str | None = None
    main_video_url: str | None = None
    includes_certification_exam: bool | None = None
    price_currency: str | None = Field(default=None, min_length=3, max_length=8)
    base_price_amount: float | None = Field(default=None, ge=0)
    gst_rate: float | None = Field(default=None, ge=0)
    platform_commission_rate: float | None = Field(default=None, ge=0)
    hosting_fee_amount: float | None = Field(default=None, ge=0)
    gst_amount: float | None = Field(default=None, ge=0)
    platform_commission_amount: float | None = Field(default=None, ge=0)
    final_price_amount: float | None = Field(default=None, ge=0)


class CourseOut(BaseModel):
    id: int
    provider_id: int
    title: str
    description: str
    category: str
    suitable_age_ranges: list[str] = Field(default_factory=list)
    thumbnail_url: str | None
    intro_video_url: str | None = None
    preview_video_url: str | None = None
    main_video_url: str | None = None
    includes_certification_exam: bool
    price_currency: str = "INR"
    base_price_amount: float = 0
    gst_rate: float = 0.18
    platform_commission_rate: float = 0.25
    hosting_fee_amount: float = 2500
    gst_amount: float = 0
    platform_commission_amount: float = 0
    final_price_amount: float = 0
    is_published: bool

    model_config = {"from_attributes": True}


class ModuleCreate(BaseModel):
    title: str
    syllabus_text: str = ""
    position: int = 1


class LessonCreate(BaseModel):
    title: str
    lesson_type: LessonType
    recorded_video_url: str | None = None
    live_class_url: str | None = None
    position: int = 1


class ResourceCreate(BaseModel):
    title: str
    url: str
    resource_type: str = "attachment"


class ExamCreate(BaseModel):
    course_id: int
    title: str
    assessment_type: AssessmentType = AssessmentType.MCQ
    instructions: str = ""
    about: str = ""
    tools: list[str] = []
    topics: list[str] = []
    duration_minutes: int = 25
    timing_mode: str = "question"
    time_per_question_seconds: int | None = 25
    questions_per_attempt: int = 25
    pass_score: float = 70
    negative_marking: bool = False
    shuffle_questions: bool = False
    shuffle_options: bool = False
    exam_window_start: datetime | None = None
    exam_window_end: datetime | None = None
    max_attempts: int = 3
    certificate_enabled: bool = True


class ExamUpdate(BaseModel):
    title: str | None = None
    assessment_type: AssessmentType | None = None
    instructions: str | None = None
    about: str | None = None
    tools: list[str] | None = None
    topics: list[str] | None = None
    duration_minutes: int | None = None
    timing_mode: str | None = None
    time_per_question_seconds: int | None = None
    questions_per_attempt: int | None = None
    pass_score: float | None = None
    negative_marking: bool | None = None
    shuffle_questions: bool | None = None
    shuffle_options: bool | None = None
    exam_window_start: datetime | None = None
    exam_window_end: datetime | None = None
    max_attempts: int | None = None
    certificate_enabled: bool | None = None


class ExamRuleUpdate(BaseModel):
    min_questions: int = 25
    min_pass_score: float = 70
    max_easy_ratio: float = 0.70
    min_syllabus_areas: int = 3
    max_duplicate_ratio: float = 0.10
    max_ambiguous_ratio: float = 0.10


class OptionCreate(BaseModel):
    option_text: str
    is_correct: bool
    position: int = 1


class QuestionCreate(BaseModel):
    question_text: str
    question_type: QuestionType
    marks: float = 1
    negative_marks: float = 0
    options: list[OptionCreate] = []


class ExamOut(BaseModel):
    id: int
    course_id: int
    title: str
    assessment_type: str = "mcq"
    instructions: str = ""
    about: str = ""
    tools: list[str] = []
    topics: list[str] = []
    duration_minutes: int
    timing_mode: str
    time_per_question_seconds: int | None = None
    questions_per_attempt: int
    total_marks: float
    pass_score: float
    max_attempts: int
    certificate_enabled: bool
    status: str
    admin_certification_approved: bool

    model_config = {"from_attributes": True}


class AssessmentTaskIn(BaseModel):
    type: AssessmentType
    title: str
    description: str = ""
    instructions: str = ""
    marks: float = 0
    metadata: dict[str, Any] = {}
    expected_output: dict[str, Any] = {}
    grading_config: dict[str, Any] = {}


class AssessmentTaskOut(BaseModel):
    id: int
    assessment_id: int
    type: str
    title: str
    description: str
    instructions: str
    marks: float
    metadata: dict[str, Any]
    expected_output: dict[str, Any]
    grading_config: dict[str, Any]


class AssessmentSubmissionIn(BaseModel):
    submitted_data: dict[str, Any] = {}
    time_taken_seconds: int | None = None
    proctoring_events: list[Any] | dict[str, Any] | None = None


class EnrollmentCreate(BaseModel):
    course_id: int


class EnrollmentOut(BaseModel):
    id: int
    student_id: int
    course_id: int
    status: str
    progress_pct: float
    exam_eligible: bool

    model_config = {"from_attributes": True}


class AttemptStartResponse(BaseModel):
    attempt_id: int
    exam_id: int
    student_id: int
    started_at: datetime


class AnswerSaveRequest(BaseModel):
    question_id: int
    selected_option_ids: list[int] | None = None
    text_answer: str | None = None


class ResultOut(BaseModel):
    id: int
    attempt_id: int
    student_id: int
    exam_id: int
    score: float
    percentage: float
    passed: bool
    correct_count: int | None = None
    wrong_count: int | None = None
    total_questions: int | None = None
    proctor_decision: str | None = None
    proctor_probability: float | None = None
    proctor_deduction_pct: float | None = None
    proctor_deduction_mode: str | None = None
    proctor_review_required: bool | None = None
    proctor_hard_fail: bool | None = None
    proctor_hard_fail_reason: str | None = None
    training_feedback_status: str | None = None
    training_feedback_comment: str | None = None
    training_feedback_count: int = 0
    certificate: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class CertificateOut(BaseModel):
    certificate_id: str
    result_id: int
    student_id: int
    course_id: int
    provider_id: int
    status: str
    issued_at: datetime
    pdf_url: str | None = None
    download_url: str | None = None
    verification_link: str


class AdminApprovalRequest(BaseModel):
    approve: bool
    rejection_reason: str | None = None


class DocumentReviewRequest(BaseModel):
    status: ApprovalStatus
    review_note: str | None = None


class EventRequest(BaseModel):
    event_type: str
    payload: dict[str, Any] = {}


class UserApprovalOut(BaseModel):
    id: int
    user_id: int
    status: ApprovalStatus
    rejection_reason: str | None

    model_config = {"from_attributes": True}


class ReportCreate(BaseModel):
    report_type: str
    details: str
    target_type: str | None = None
    target_id: int | None = None


class ComplaintCreate(BaseModel):
    complaint_type: str
    details: str


class ModerationUpdateRequest(BaseModel):
    status: ModerationStatus


class AnalyticsOut(BaseModel):
    onboarded_providers: int
    approved_students: int
    enrolled_courses: int
    issued_certificates: int
    pass_percentage: float


class ProviderHomeOut(BaseModel):
    total_courses: int
    published_courses: int
    total_enrollments: int
    exams_created: int
    certificates_issued: int
    pass_percentage: float
    unread_notifications: int


class LessonTopicCreate(BaseModel):
    title: str
    time_seconds: int = Field(ge=0)
    thumbnail_data_url: str | None = None


class LessonTopicOut(BaseModel):
    id: int
    lesson_id: int
    title: str
    time_seconds: int
    thumbnail_data_url: str | None = None

    model_config = {"from_attributes": True}


class ProctorSessionStartRequest(BaseModel):
    mode: str = "attempt"  # attempt | preview
    exam_id: int | None = None
    attempt_id: int | None = None
    consent_camera: bool = False
    consent_microphone: bool = False
    consent_recording: bool = False


class ProctorEventCreate(BaseModel):
    event_type: str
    severity: str = "info"  # info | warning | critical
    confidence: float | None = None
    details: dict = {}


class ProctorFinalizeRequest(BaseModel):
    ended_reason: str | None = None


class ProctorReviewRequest(BaseModel):
    review_status: str = "reviewed"  # reviewed | actioned
    notes: str | None = None


class ProctorTrainingFeedbackCreate(BaseModel):
    training_result: str = "correct"  # correct | incorrect
    comment: str | None = None


class ProctorDatasetSourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    source_type: str = "local_csv"  # local_csv | local_dir | s3_prefix
    source_path: str = Field(min_length=1, max_length=1000)
    is_enabled: bool = True
    notes: str | None = None


class ProctorDatasetSourceUpdate(BaseModel):
    source_type: str | None = None
    source_path: str | None = None
    is_enabled: bool | None = None
    notes: str | None = None


class ProctorModelTrainRequest(BaseModel):
    minimum_samples: int = Field(default=30, ge=10, le=50000)
    validation_split: float = Field(default=0.2, ge=0.1, le=0.5)
    target_recall: float = Field(default=0.92, ge=0.5, le=0.99)
    max_false_positive_rate: float = Field(default=0.30, ge=0.05, le=0.8)
    strict_mode: bool = True
    class_balance_strength: float = Field(default=1.0, ge=0.0, le=1.5)
    hard_negative_weight: float = Field(default=2.0, ge=1.0, le=6.0)
    hard_positive_weight: float = Field(default=1.6, ge=1.0, le=6.0)
    hard_example_min_prob: float = Field(default=0.55, ge=0.5, le=0.9)
    curated_hard_negative_weight: float = Field(default=2.6, ge=1.0, le=10.0)
    max_curated_hard_negatives: int = Field(default=800, ge=0, le=50000)


class ProctorHardNegativeIngestRequest(BaseModel):
    lookback_days: int = Field(default=45, ge=1, le=3650)
    limit: int = Field(default=1000, ge=1, le=20000)
    min_model_probability: float = Field(default=0.45, ge=0.0, le=1.0)
    include_preview_sessions: bool = False


class CourseCommentCreate(BaseModel):
    message: str


class CourseCommentReply(BaseModel):
    reply: str


class ProviderComplaintStatusUpdate(BaseModel):
    status: str


class ProviderFeedbackSeenUpdate(BaseModel):
    seen: bool = True


class CourseFeedbackCreate(BaseModel):
    valuable_time_rating: int = Field(ge=1, le=5)
    content_quality_rating: int = Field(ge=1, le=5)
    instructor_clarity_rating: int = Field(ge=1, le=5)
    practical_usefulness_rating: int = Field(ge=1, le=5)
    comment: str | None = None


class LiveClassScheduleCreate(BaseModel):
    course_id: int | None = None
    title: str = Field(min_length=2, max_length=255)
    description: str | None = None
    scheduled_start_at: datetime
    scheduled_end_at: datetime | None = None
    timezone: str = "UTC"
    meeting_mode: str = "in_app"  # in_app | external
    external_meeting_url: str | None = None
    max_participants: int = Field(default=200, ge=1, le=2000)
    allow_chat: bool = True
    allow_raise_hand: bool = True
    allow_reactions: bool = True
    recurrence_pattern: str = "none"  # none | daily | weekly | weekends | custom
    recurrence_count: int = Field(default=1, ge=1, le=60)
    recurrence_custom_days: list[int] = []


class LiveClassScheduleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    scheduled_start_at: datetime | None = None
    scheduled_end_at: datetime | None = None
    timezone: str | None = None
    meeting_mode: str | None = None  # in_app | external
    external_meeting_url: str | None = None
    max_participants: int | None = Field(default=None, ge=1, le=2000)
    allow_chat: bool | None = None
    allow_raise_hand: bool | None = None
    allow_reactions: bool | None = None
    recurrence_pattern: str | None = None
    recurrence_count: int | None = Field(default=None, ge=1, le=60)
    recurrence_custom_days: list[int] | None = None


class LiveClassMessageCreate(BaseModel):
    message_type: str = "chat"  # chat | announcement | reaction
    content: str = Field(min_length=1, max_length=2000)
    payload: dict = {}


class LiveClassBoardUpdate(BaseModel):
    board_text: str = Field(min_length=0, max_length=12000)


class LiveClassPollCreate(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    options: list[str] = Field(min_length=2, max_length=8)


class LiveClassPollVoteCreate(BaseModel):
    option_index: int = Field(ge=0, le=7)


class LiveClassHostAction(BaseModel):
    action: str = Field(min_length=2, max_length=40)  # admit|reject|remove|mute|unmute|assign_breakout|clear_breakouts|toggle_waiting_room
    target_user_id: int | None = None
    room: str | None = None
    enabled: bool | None = None


class StreamCourseCreate(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    description: str = ""
    category: str = "General"
    fair_usage_multiplier: float | None = None


class StreamLessonCreate(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    position: int = Field(default=1, ge=1)


class StreamVideoUploadInitRequest(BaseModel):
    lesson_id: int
    max_duration_seconds: int | None = Field(default=None, ge=30, le=86400)


class StreamVideoUploadInitResponse(BaseModel):
    lesson_video_id: int
    internal_id: str
    cloudflare_video_uid: str
    upload_url: str
    expires_at: datetime | None = None
    status: str


class StreamPurchaseRequest(BaseModel):
    course_id: int
    price_amount: float = Field(ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=8)
    payment_ref: str | None = Field(default=None, max_length=120)


class StreamPlaybackTokenRequest(BaseModel):
    lesson_video_id: int
    client_app: str = Field(default="web", max_length=30)


class StreamWatchHeartbeatRequest(BaseModel):
    session_id: int
    lesson_video_id: int
    watched_seconds_delta: int = Field(ge=0, le=120)
    position_seconds: int = Field(ge=0)
    player_state: str | None = Field(default=None, max_length=40)
    drm_license_token: str | None = Field(default=None, min_length=16, max_length=4096)
    drm_heartbeat_nonce: str | None = Field(default=None, min_length=8, max_length=120)
    ended: bool = False


class StreamLicenseIssueRequest(BaseModel):
    session_id: int
    lesson_video_id: int
    client_app: str = Field(default="web", max_length=30)


class StreamLicenseIssueResponse(BaseModel):
    license_token: str
    expires_in_seconds: int


class StreamSessionRevokeRequest(BaseModel):
    reason: str = Field(default="admin_revoke", min_length=3, max_length=240)


class StreamBulkRevokeRequest(BaseModel):
    course_id: int | None = None
    reason: str = Field(default="security_incident", min_length=3, max_length=240)


class StreamPricingRecommendationRequest(BaseModel):
    entered_price: float = Field(ge=0)
    expected_views_per_month: int = Field(default=100, ge=1, le=1000000)


class StreamLiveSessionCreate(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    course_id: int | None = None
    scheduled_start_at: datetime | None = None


class StreamFairUsageOverrideRequest(BaseModel):
    fair_usage_multiplier: float | None = Field(default=None, ge=0.1, le=20.0)
    override_seconds: int | None = Field(default=None, ge=60)
    override_enabled: bool = False
