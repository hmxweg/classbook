from pydantic import BaseModel
from typing import Optional
from datetime import date
from typing import List

# 登录请求的数据格式
class LoginRequest(BaseModel):
    device_hash: str

# 绑定身份请求的数据格式
class BindRequest(BaseModel):
    device_hash: str
    student_id: int
    relation: str  # 比如：爸爸、妈妈

# 单个任务的内容
class TaskItem(BaseModel):
    content: str

# 批量发布作业的请求格式
class TaskCreateRequest(BaseModel):
    user_id: int         # 实际开发中应该从 Token 中解析，这里为了测试方便由前端直接传
    subject_id: int
    target_date: date    # 对应您要求的“目标日期”
    tasks: List[TaskItem] # 允许一次性提交最多 5 个任务


# 点赞请求的数据格式
class TaskLikeRequest(BaseModel):
    user_id: int  # 同样，实际开发中应从 Header 的 Token 中解析，这里为了方便测试让前端传

# 锁定任务请求的数据格式
class TaskLockRequest(BaseModel):
    admin_password: str  # 管理员密码

# 修改任务请求的数据格式
class TaskUpdateRequest(BaseModel):
    user_id: int
    content: str

# 验证邀请码请求的数据格式
class VerifyCodeRequest(BaseModel):
    code: str