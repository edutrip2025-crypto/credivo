from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class UserRole(StrEnum):
    STUDENT = "student"
    PROVIDER = "provider"
    ADMIN = "admin"


class ProviderType(StrEnum):
    INDIVIDUAL = "individual_instructor"
    BUSINESS = "business_institute_brand"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentType(StrEnum):
    KYC = "kyc_document"
    BUSINESS = "business_document"


class LessonType(StrEnum):
    RECORDED = "recorded_video"
    LIVE = "live_class_link"


class QuestionType(StrEnum):
    MCQ_SINGLE = "mcq_single_correct"
    MCQ_MULTI = "mcq_multiple_correct"
    SHORT_ANSWER = "short_answer"


class AssessmentType(StrEnum):
    MCQ = "mcq"
    CODING = "coding"
    SPREADSHEET = "spreadsheet"
    TAX_SIMULATOR = "tax_simulator"
    CASE_STUDY = "case_study"


class ExamStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
    REJECTED = "rejected"


class AttemptStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"


class EnrollmentStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CertificateStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class AiJobStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ModerationStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), index=True)
    student_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    account_state: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active | frozen | banned | deleted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BannedIdentity(Base):
    __tablename__ = "banned_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    id_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    id_number: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    source_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserIdentityVerification(Base):
    __tablename__ = "user_identity_verifications"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_identity_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    id_type: Mapped[str] = mapped_column(String(40), index=True)
    id_number: Mapped[str] = mapped_column(String(120))
    country_code: Mapped[str] = mapped_column(String(8), default="IN")
    document_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING, index=True)
    reviewed_by_admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProviderProfile(Base):
    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    provider_type: Mapped[ProviderType] = mapped_column(Enum(ProviderType))
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    business_registration_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    business_registration_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    business_registration_country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProviderDocument(Base):
    __tablename__ = "provider_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    document_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType))
    file_url: Mapped[str] = mapped_column(String(1000))
    status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserApproval(Base):
    __tablename__ = "user_approvals"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_approval_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100), index=True)
    suitable_age_ranges: Mapped[list] = mapped_column(JSON, default=list)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    intro_video_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    preview_video_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    main_video_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    includes_certification_exam: Mapped[bool] = mapped_column(Boolean, default=False)
    fair_usage_multiplier: Mapped[float] = mapped_column(Float, default=2.5)
    fair_usage_override_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    admin_fair_usage_override_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    price_currency: Mapped[str] = mapped_column(String(8), default="INR")
    base_price_amount: Mapped[float] = mapped_column(Float, default=0)
    gst_rate: Mapped[float] = mapped_column(Float, default=0.18)
    platform_commission_rate: Mapped[float] = mapped_column(Float, default=0.25)
    hosting_fee_amount: Mapped[float] = mapped_column(Float, default=2500)
    gst_amount: Mapped[float] = mapped_column(Float, default=0)
    platform_commission_amount: Mapped[float] = mapped_column(Float, default=0)
    final_price_amount: Mapped[float] = mapped_column(Float, default=0)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Creator(Base):
    __tablename__ = "creators"
    __table_args__ = (UniqueConstraint("user_id", name="uq_creator_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CourseLesson(Base):
    __tablename__ = "course_lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=1)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CoursePurchase(Base):
    __tablename__ = "course_purchases"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_course_purchase_user_course"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    price_amount: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    payment_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="paid", index=True)
    admin_override: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LessonVideo(Base):
    __tablename__ = "lesson_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("course_lessons.id"), index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), index=True)
    internal_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cloudflare_video_uid: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    upload_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    ready_status: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    playback_hls_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    direct_upload_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class VideoWatchSession(Base):
    __tablename__ = "video_watch_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("course_lessons.id"), index=True)
    lesson_video_id: Mapped[int] = mapped_column(ForeignKey("lesson_videos.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_position_seconds: Mapped[int] = mapped_column(Integer, default=0)
    client_app: Mapped[str] = mapped_column(String(30), default="web")
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)


class VideoWatchProgress(Base):
    __tablename__ = "video_watch_progress"
    __table_args__ = (UniqueConstraint("user_id", "lesson_video_id", name="uq_video_watch_progress_user_video"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("course_lessons.id"), index=True)
    lesson_video_id: Mapped[int] = mapped_column(ForeignKey("lesson_videos.id"), index=True)
    total_watched_seconds: Mapped[int] = mapped_column(Integer, default=0)
    resume_position_seconds: Mapped[int] = mapped_column(Integer, default=0)
    completion_ratio: Mapped[float] = mapped_column(Float, default=0)
    first_watched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_watched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    usage_warning_level: Mapped[int] = mapped_column(Integer, default=0)


class LiveStreamSession(Base):
    __tablename__ = "live_stream_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    cloudflare_input_id: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    cloudflare_live_uid: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    scheduled_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CourseModule(Base):
    __tablename__ = "course_modules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    syllabus_text: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=1)


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("course_modules.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    lesson_type: Mapped[LessonType] = mapped_column(Enum(LessonType))
    recorded_video_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    live_class_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=1)


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    module_id: Mapped[int | None] = mapped_column(ForeignKey("course_modules.id"), nullable=True)
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("lessons.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(1000))
    resource_type: Mapped[str] = mapped_column(String(50), default="attachment")


class InstructorMapping(Base):
    __tablename__ = "instructor_mappings"
    __table_args__ = (UniqueConstraint("course_id", "instructor_user_id", name="uq_course_instructor"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    instructor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    assessment_type: Mapped[str] = mapped_column(String(30), default=AssessmentType.MCQ.value, index=True)
    instructions: Mapped[str] = mapped_column(Text, default="")
    assessment_about: Mapped[str] = mapped_column(Text, default="")
    tools_json: Mapped[list] = mapped_column(JSON, default=list)
    topics_json: Mapped[list] = mapped_column(JSON, default=list)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=25)
    timing_mode: Mapped[str] = mapped_column(String(20), default="assessment")
    time_per_question_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    questions_per_attempt: Mapped[int] = mapped_column(Integer, default=0)
    total_marks: Mapped[float] = mapped_column(Float, default=0)
    pass_score: Mapped[float] = mapped_column(Float, default=70)
    negative_marking: Mapped[bool] = mapped_column(Boolean, default=False)
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, default=False)
    shuffle_options: Mapped[bool] = mapped_column(Boolean, default=False)
    exam_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exam_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    certificate_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[ExamStatus] = mapped_column(Enum(ExamStatus), default=ExamStatus.DRAFT)
    admin_certification_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    @property
    def about(self) -> str:
        return self.assessment_about or ""

    @property
    def tools(self) -> list:
        return list(self.tools_json or [])

    @property
    def topics(self) -> list:
        return list(self.topics_json or [])


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    question_text: Mapped[str] = mapped_column(Text)
    question_type: Mapped[QuestionType] = mapped_column(Enum(QuestionType), default=QuestionType.MCQ_SINGLE)
    marks: Mapped[float] = mapped_column(Float, default=1)
    negative_marks: Mapped[float] = mapped_column(Float, default=0)
    difficulty_tag: Mapped[str | None] = mapped_column(String(20), nullable=True)

    options: Mapped[list["Option"]] = relationship(back_populates="question", cascade="all, delete-orphan")


class Option(Base):
    __tablename__ = "options"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    option_text: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=1)

    question: Mapped[Question] = relationship(back_populates="options")


class ExamRule(Base):
    __tablename__ = "exam_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), unique=True, index=True)
    min_questions: Mapped[int] = mapped_column(Integer, default=25)
    min_pass_score: Mapped[float] = mapped_column(Float, default=60)
    max_easy_ratio: Mapped[float] = mapped_column(Float, default=0.70)
    min_syllabus_areas: Mapped[int] = mapped_column(Integer, default=3)
    max_duplicate_ratio: Mapped[float] = mapped_column(Float, default=0.10)
    max_ambiguous_ratio: Mapped[float] = mapped_column(Float, default=0.10)


class AiReviewJob(Base):
    __tablename__ = "ai_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), unique=True, index=True)
    status: Mapped[AiJobStatus] = mapped_column(Enum(AiJobStatus), default=AiJobStatus.PENDING)
    difficulty_easy_pct: Mapped[float] = mapped_column(Float, default=0)
    difficulty_medium_pct: Mapped[float] = mapped_column(Float, default=0)
    difficulty_hard_pct: Mapped[float] = mapped_column(Float, default=0)
    clarity_score: Mapped[float] = mapped_column(Float, default=0)
    duplication_risk: Mapped[float] = mapped_column(Float, default=0)
    syllabus_coverage_estimate: Mapped[float] = mapped_column(Float, default=0)
    certification_readiness_score: Mapped[float] = mapped_column(Float, default=0)
    flagged_questions_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str] = mapped_column(Text, default="")
    flags_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("student_id", "course_id", name="uq_student_course_enrollment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    status: Mapped[EnrollmentStatus] = mapped_column(Enum(EnrollmentStatus), default=EnrollmentStatus.ACTIVE)
    progress_pct: Mapped[float] = mapped_column(Float, default=0)
    exam_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[AttemptStatus] = mapped_column(Enum(AttemptStatus), default=AttemptStatus.IN_PROGRESS)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0)
    percentage: Mapped[float] = mapped_column(Float, default=0)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    assigned_question_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)


class AssessmentIssue(Base):
    __tablename__ = "assessment_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    issuer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    candidate_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    candidate_name: Mapped[str] = mapped_column(String(200))
    candidate_email: Mapped[str] = mapped_column(String(320), index=True)
    candidate_password_hash: Mapped[str] = mapped_column(String(255))
    access_key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    credential_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="issued", index=True)  # issued | started | completed
    score_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssessmentTask(Base):
    __tablename__ = "assessment_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")
    marks: Mapped[float] = mapped_column(Float, default=0)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    grading_config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AssessmentSubmission(Base):
    __tablename__ = "assessment_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    issue_id: Mapped[int | None] = mapped_column(ForeignKey("assessment_issues.id"), nullable=True, index=True)
    assessment_type: Mapped[str] = mapped_column(String(30), index=True)
    submitted_data_json: Mapped[dict] = mapped_column(JSON, default=dict)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    auto_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="submitted", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_taken_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proctoring_events_json: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StudentAnswer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", name="uq_attempt_question_answer"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("exam_attempts.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    selected_option_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    text_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    awarded_marks: Mapped[float] = mapped_column(Float, default=0)


class AttemptEvent(Base):
    __tablename__ = "attempt_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("exam_attempts.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProctorSession(Base):
    __tablename__ = "proctor_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    mode: Mapped[str] = mapped_column(String(20), default="attempt")  # attempt | preview
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | completed | terminated
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id"), nullable=True, index=True)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("exam_attempts.id"), nullable=True, index=True)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_score: Mapped[float] = mapped_column(Float, default=0)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    ended_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    admin_review_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | reviewed | actioned
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProctorEvent(Base):
    __tablename__ = "proctor_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("proctor_sessions.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    severity: Mapped[str] = mapped_column(String(20), default="info")  # info | warning | critical
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProctorEvidence(Base):
    __tablename__ = "proctor_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("proctor_sessions.id"), index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("proctor_events.id"), nullable=True, index=True)
    evidence_type: Mapped[str] = mapped_column(String(40), default="image")  # image | audio | video | log
    file_url: Mapped[str] = mapped_column(String(1000))
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProctorTrainingFeedback(Base):
    __tablename__ = "proctor_training_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("exam_attempts.id"), nullable=True, index=True)
    result_id: Mapped[int | None] = mapped_column(ForeignKey("results.id"), nullable=True, index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("proctor_sessions.id"), nullable=True, index=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    feedback_label: Mapped[str] = mapped_column(String(20), default="correct")  # correct | incorrect
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_decision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_result_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProctorDatasetSource(Base):
    __tablename__ = "proctor_dataset_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    source_type: Mapped[str] = mapped_column(String(30), default="local_csv")  # local_csv | local_dir | s3_prefix
    source_path: Mapped[str] = mapped_column(String(1000))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProctorModelRun(Base):
    __tablename__ = "proctor_model_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    model_key: Mapped[str] = mapped_column(String(80), default="logistic", index=True)
    feature_space: Mapped[str] = mapped_column(String(80), default="event_risk_v1")
    status: Mapped[str] = mapped_column(String(20), default="completed", index=True)  # queued | running | completed | failed
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_count: Mapped[int] = mapped_column(Integer, default=0)
    precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    f1_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    roc_auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    warning_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_review_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Result(Base):
    __tablename__ = "results"
    __table_args__ = (UniqueConstraint("attempt_id", name="uq_attempt_result"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("exam_attempts.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    percentage: Mapped[float] = mapped_column(Float)
    passed: Mapped[bool] = mapped_column(Boolean)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CertificateTemplate(Base):
    __tablename__ = "certificate_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="default")
    branding_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("results.id"), unique=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    certificate_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    verification_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    pdf_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[CertificateStatus] = mapped_column(Enum(CertificateStatus), default=CertificateStatus.ACTIVE)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VerificationRecord(Base):
    __tablename__ = "verification_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    certificate_id: Mapped[int] = mapped_column(ForeignKey("certificates.id"), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReportItem(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    reporter_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    report_type: Mapped[str] = mapped_column(String(120), index=True)
    details: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[ModerationStatus] = mapped_column(Enum(ModerationStatus), default=ModerationStatus.OPEN, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ComplaintItem(Base):
    __tablename__ = "complaints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    complainant_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    complaint_type: Mapped[str] = mapped_column(String(120), index=True)
    details: Mapped[str] = mapped_column(Text)
    status: Mapped[ModerationStatus] = mapped_column(Enum(ModerationStatus), default=ModerationStatus.OPEN, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str] = mapped_column(String(80), index=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LessonTopic(Base):
    __tablename__ = "lesson_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("lessons.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    time_seconds: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail_data_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CourseComment(Base):
    __tablename__ = "course_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    provider_status: Mapped[str] = mapped_column(String(20), default="new", index=True)  # new | pending | closed
    provider_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CourseFeedback(Base):
    __tablename__ = "course_feedback"
    __table_args__ = (UniqueConstraint("course_id", "student_id", name="uq_course_feedback_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    valuable_time_rating: Mapped[int] = mapped_column(Integer, default=5)
    content_quality_rating: Mapped[int] = mapped_column(Integer, default=5)
    instructor_clarity_rating: Mapped[int] = mapped_column(Integer, default=5)
    practical_usefulness_rating: Mapped[int] = mapped_column(Integer, default=5)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CourseCompletion(Base):
    __tablename__ = "course_completions"
    __table_args__ = (UniqueConstraint("course_id", "student_id", name="uq_course_completion_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LiveClassCompletion(Base):
    __tablename__ = "live_class_completions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class LiveClassSession(Base):
    __tablename__ = "live_class_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    room_code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    meeting_mode: Mapped[str] = mapped_column(String(20), default="in_app")  # in_app | external
    external_meeting_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled | live | ended | cancelled
    scheduled_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    scheduled_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_participants: Mapped[int] = mapped_column(Integer, default=200)
    allow_chat: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_raise_hand: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_reactions: Mapped[bool] = mapped_column(Boolean, default=True)
    board_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_poll_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active_poll_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_poll_options_json: Mapped[list] = mapped_column(JSON, default=list)
    active_poll_open: Mapped[bool] = mapped_column(Boolean, default=False)
    recurrence_pattern: Mapped[str] = mapped_column(String(20), default="none")  # none|daily|weekly|weekends|custom
    recurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    recurrence_custom_days_json: Mapped[list] = mapped_column(JSON, default=list)  # 0=Mon..6=Sun
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class LiveClassParticipant(Base):
    __tablename__ = "live_class_participants"
    __table_args__ = (UniqueConstraint("session_id", "user_id", name="uq_live_class_participant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("live_class_sessions.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    actor_role: Mapped[str] = mapped_column(String(20), default="student")  # provider | student
    display_name: Mapped[str] = mapped_column(String(200))
    is_present: Mapped[bool] = mapped_column(Boolean, default=True)
    raised_hand: Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LiveClassMessage(Base):
    __tablename__ = "live_class_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("live_class_sessions.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message_type: Mapped[str] = mapped_column(String(30), default="chat")
    content: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class LiveClassPollVote(Base):
    __tablename__ = "live_class_poll_votes"
    __table_args__ = (UniqueConstraint("session_id", "poll_key", "user_id", name="uq_live_class_poll_vote"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("live_class_sessions.id"), index=True)
    poll_key: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    option_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProviderNotification(Base):
    __tablename__ = "provider_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    message: Mapped[str] = mapped_column(Text)
    ref_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VideoUploadStatus(StrEnum):
    INITIATED = "initiated"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoUploadSession(Base):
    __tablename__ = "video_upload_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    total_size: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    received_chunks: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[VideoUploadStatus] = mapped_column(Enum(VideoUploadStatus), default=VideoUploadStatus.INITIATED)
    file_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProviderCourseDraft(Base):
    __tablename__ = "provider_course_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    level: Mapped[str] = mapped_column(String(50), default="Beginner")
    category: Mapped[str] = mapped_column(String(100), default="General")
    suitable_age_ranges: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    includes_exam: Mapped[bool] = mapped_column(Boolean, default=True)
    intro_video_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    base_price_amount: Mapped[float] = mapped_column(Float, default=0)
    price_currency: Mapped[str] = mapped_column(String(8), default="INR")
    gst_rate: Mapped[float] = mapped_column(Float, default=0.18)
    platform_commission_rate: Mapped[float] = mapped_column(Float, default=0.25)
    hosting_fee_amount: Mapped[float] = mapped_column(Float, default=2500)
    gst_amount: Mapped[float] = mapped_column(Float, default=0)
    platform_commission_amount: Mapped[float] = mapped_column(Float, default=0)
    final_price_amount: Mapped[float] = mapped_column(Float, default=0)
    topics_json: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
