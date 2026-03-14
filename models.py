from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.sql import func
from database import Base
from sqlalchemy import Boolean, Date

class Student(Base):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, index=True)
    pinyin = Column(String(100))
    status = Column(Boolean, default=True)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    device_hash = Column(String(128), unique=True, nullable=False)
    student_id = Column(Integer, nullable=False, index=True)
    relation = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Subject(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    icon = Column(String(50))
    is_default = Column(Boolean, default=False)
    sort_order = Column(Integer, default=0)

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    subject_id = Column(Integer, nullable=False)
    target_date = Column(DateTime, nullable=False, index=True) # 核心：作业所属日期
    user_id = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    like_count = Column(Integer, default=0)
    similarity_group_id = Column(String(64), nullable=False)
    is_locked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_date_subject', 'target_date', 'subject_id'),
    )

class TaskLike(Base):
    __tablename__ = "task_likes"
    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, nullable=False)
    user_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    __table_args__ = (
        UniqueConstraint('task_id', 'user_id', name='uk_task_user'),
    )

# ----------------------------
# 系统配置表 (用于存储邀请码、管理密码等全局设置)
# ----------------------------
class ClassConfig(Base):
    __tablename__ = "class_configs"

    id = Column(Integer, primary_key=True, index=True)
    invite_code = Column(String(50), nullable=False, default="666666") # 班级邀请码
    lock_password = Column(String(50), nullable=False, default="888888") # 新增：锁定作业的管理密码

# ----------------------------
# 节假日/工作日历表
# ----------------------------
class CalendarDay(Base):
    __tablename__ = "calendar_days"

    # 日期作为主键，例如 "2026-03-13"
    date = Column(Date, primary_key=True, index=True) 
    # 是否为工作日 (True: 允许布置作业, False: 休息日禁发布)
    is_workday = Column(Boolean, nullable=False, default=True)