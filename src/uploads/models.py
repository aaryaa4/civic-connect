import enum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey, Enum, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class UserRole(str, enum.Enum):
    user = "user"
    admin = "admin"

class ReportCategory(str, enum.Enum):
    waste = "waste"
    traffic = "traffic"
    infra = "infra"
    other = "other"

class ReportStatus(str, enum.Enum):
    pending = "pending"
    resolved = "resolved"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    community_id = Column(Integer, ForeignKey("communities.id"))
    is_active = Column(Boolean, default=True)
    role = Column(Enum(UserRole), default=UserRole.user)
    
    community = relationship("Community", back_populates="members")
    reports = relationship("Report", back_populates="owner")
    feedback = relationship("Feedback", back_populates="owner")

class Community(Base):
    __tablename__ = "communities"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    city = Column(String)

    members = relationship("User", back_populates="community")
    reports = relationship("Report", back_populates="community")

class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, index=True)
    caption = Column(String, index=True)
    image_url = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    category = Column(Enum(ReportCategory))
    status = Column(Enum(ReportStatus), default=ReportStatus.pending)
    is_emergency = Column(Boolean, default=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    owner_id = Column(Integer, ForeignKey("users.id"))
    community_id = Column(Integer, ForeignKey("communities.id"))
    
    owner = relationship("User", back_populates="reports")
    community = relationship("Community", back_populates="reports")
    feedback = relationship("Feedback", back_populates="report", uselist=False)

class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True, index=True)
    rating = Column(Integer)
    comment = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    report_id = Column(Integer, ForeignKey("reports.id"), unique=True)
    owner_id = Column(Integer, ForeignKey("users.id"))

    report = relationship("Report", back_populates="feedback")
    owner = relationship("User", back_populates="feedback")