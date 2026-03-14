from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import engine, get_db
import models
import schemas
import uuid
import difflib
import datetime
from datetime import date, datetime, timedelta, timezone
import calendar



# 自动建表（如果表已存在则不会重复创建）
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="班书 (ClassBook) API")

# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# 基础测试接口
# ----------------------------
@app.get("/")
async def root():
    return {"message": "欢迎来到班书后端服务！表结构已自动初始化。"}

# ----------------------------
# 开发者辅助接口：初始化测试学生数据
# ----------------------------
@app.post("/api/dev/init-students", summary="[开发专用] 写入测试学生数据")
def init_test_students(db: Session = Depends(get_db)):
    # 如果已经有数据就不再插入
    if db.query(models.Student).first():
        return {"message": "学生数据已存在，无需重复初始化"}
    
    test_students = [
        models.Student(name="李小明", pinyin="lixiaoming"),
        models.Student(name="李华", pinyin="lihua"),
        models.Student(name="张伟", pinyin="zhangwei"),
        models.Student(name="王芳", pinyin="wangfang")
    ]
    db.add_all(test_students)
    db.commit()
    return {"message": "测试学生数据初始化成功！"}

# ----------------------------
# 业务接口：验证班级邀请码 (动态读取 MySQL)
# ----------------------------
@app.post("/api/auth/verify-invite", summary="验证班级邀请码")
def verify_invite_code(request: schemas.VerifyCodeRequest, db: Session = Depends(get_db)):
    # 1. 从数据库中查询配置表的第一条记录
    config = db.query(models.ClassConfig).first()
    
    # 2. 如果没存（系统刚初始化），则自动建一条并存入数据库
    if not config:
        config = models.ClassConfig(invite_code="666666")
        db.add(config)
        db.commit()
        db.refresh(config)
    
    # 3. 动态比对用户输入和数据库中存储的邀请码
    if request.code == config.invite_code:
        return {"code": 200, "message": "验证成功"}
    else:
        raise HTTPException(status_code=403, detail="班级邀请码错误，请联系管理员获取！")


# ----------------------------
# 业务接口：二次验证本地身份是否合法 (防止后端被删，前端残留缓存)
# ----------------------------
@app.get("/api/auth/verify-auth", summary="动态核验身份存活性")
def verify_local_auth(user_id: int, device_hash: str, db: Session = Depends(get_db)):
    # 去 users 表里查一下，这个 user_id 和设备 hash 是否还能对得上
    user = db.query(models.User).filter(
        models.User.id == user_id, 
        models.User.device_hash == device_hash
    ).first()
    
    if not user:
        # 如果查不到，说明管理员在后台删了数据，直接抛出 401 无权限异常
        raise HTTPException(status_code=401, detail="身份已失效，请重新验证")
        
    return {"code": 200, "message": "身份合法"}

# 核心规则：判断某天是否是工作日 (带自动初始化)
# ----------------------------
def check_is_workday(db: Session, target_date: date) -> bool:
    cal_day = db.query(models.CalendarDay).filter(models.CalendarDay.date == target_date).first()
    
    # 智能容错：如果数据库里还没录入这一天，自动根据周一到周五推断，并写入数据库
    if not cal_day:
        is_wd = target_date.weekday() < 5 # 0-4代表周一到周五
        cal_day = models.CalendarDay(date=target_date, is_workday=is_wd)
        db.add(cal_day)
        db.commit()
        
    return cal_day.is_workday

# ----------------------------
# 业务接口 1：设备哈希登录校验 (对应页面①)
# ----------------------------
@app.post("/api/auth/login", summary="设备免密登录")
def login(request: schemas.LoginRequest, db: Session = Depends(get_db)):
    # 去数据库里找这个 device_hash
    user = db.query(models.User).filter(models.User.device_hash == request.device_hash).first()
    
    if user:
        # 找到了，说明已经绑定过，顺便查出孩子的名字返回给前端
        student = db.query(models.Student).filter(models.Student.id == user.student_id).first()
        return {
            "code": 200, 
            "data": {
                "need_binding": False,
                "user_id": user.id,
                "student_name": student.name if student else "未知",
                "relation": user.relation
            }
        }
    else:
        # 没找到，告诉前端需要跳转到页面②去绑定
        return {"code": 200, "data": {"need_binding": True}}

# ----------------------------
# 业务接口 2：学生姓名模糊搜索 (对应页面②)
# ----------------------------
@app.get("/api/students/search", summary="模糊搜索学生姓名")
def search_students(keyword: str, db: Session = Depends(get_db)):
    if not keyword:
        return {"code": 200, "data": []}
    
    # 巧妙利用 SQLAlchemy 进行 name 或 pinyin 的模糊匹配
    students = db.query(models.Student).filter(
        (models.Student.name.like(f"%{keyword}%")) | 
        (models.Student.pinyin.like(f"%{keyword}%"))
    ).all()
    
    # 组装返回给前端下拉列表的数据
    result = [{"id": s.id, "name": s.name} for s in students]
    return {"code": 200, "data": result}

# ----------------------------
# 业务接口 3：提交身份绑定 (对应页面②的“确认绑定”按钮)
# ----------------------------
@app.post("/api/auth/bind", summary="提交身份绑定")
def bind_identity(request: schemas.BindRequest, db: Session = Depends(get_db)):
    # 1. 确认该设备是不是真的没绑过
    existing_user = db.query(models.User).filter(models.User.device_hash == request.device_hash).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="该设备已绑定过身份，请勿重复绑定")
    
    # 2. 确认选择的学生存不存在
    student = db.query(models.Student).filter(models.Student.id == request.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="未找到该学生信息")
        
    # 3. 创建绑定记录并写入数据库
    new_user = models.User(
        device_hash=request.device_hash,
        student_id=request.student_id,
        relation=request.relation
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {"code": 200, "message": "身份绑定成功！", "data": {"user_id": new_user.id}}

# ----------------------------
# 开发者辅助接口：初始化默认科目
# ----------------------------
@app.post("/api/dev/init-subjects", summary="[开发专用] 初始化默认科目")
def init_test_subjects(db: Session = Depends(get_db)):
    if db.query(models.Subject).first():
        return {"message": "科目数据已存在"}
    
    default_subjects = [
        models.Subject(name="语文", icon="fa-book", is_default=True, sort_order=1),
        models.Subject(name="数学", icon="fa-calculator", is_default=True, sort_order=2),
        models.Subject(name="英语", icon="fa-font", is_default=True, sort_order=3),
        models.Subject(name="科学", icon="fa-flask", is_default=True, sort_order=4)
    ]
    db.add_all(default_subjects)
    db.commit()
    return {"message": "默认科目初始化成功！"}

# ----------------------------
# 业务接口 8：获取科目列表 (供前端动态渲染 Tabs)
# ----------------------------
@app.get("/api/subjects", summary="获取科目列表")
def get_subjects(db: Session = Depends(get_db)):
    # 按 sort_order 排序查出所有科目
    subjects = db.query(models.Subject).order_by(models.Subject.sort_order).all()
    
    # 将 SQLAlchemy 对象手动转成干净的 Python 字典数组，防止 500 报错
    result = [{"id": s.id, "name": s.name, "icon": s.icon} for s in subjects]
    
    return {"code": 200, "data": result}

# ----------------------------
# 核心算法：计算两段文本的相似度 (返回 0.0 ~ 1.0 的浮点数)
# ----------------------------
def calculate_similarity(text1: str, text2: str) -> float:
    # difflib.SequenceMatcher 是 Python 内置的超强文本比对工具
    return difflib.SequenceMatcher(None, text1, text2).ratio()


# ----------------------------
# 核心规则：判断某天是否允许新增/修改作业
# ----------------------------
def check_is_editable(db: Session, subject_id: int, target_date: date) -> bool:
    # 🌟 [核心拦截]：一票否决！如果日历上不是工作日，直接不允许发作业！
    if not check_is_workday(db, target_date):
        return False

    bj_tz = timezone(timedelta(hours=8))
    today = datetime.now(bj_tz).date()
    
    # 计算“上一个工作日”
    if today.weekday() == 0: 
        prev_workday = today - timedelta(days=3)
    elif today.weekday() == 6: 
        prev_workday = today - timedelta(days=2)
    else: 
        prev_workday = today - timedelta(days=1)
        
    if target_date >= prev_workday:
        return True
        
    recent_dates_query = db.query(models.Task.target_date)\
                           .filter(models.Task.subject_id == subject_id)\
                           .distinct()\
                           .order_by(desc(models.Task.target_date))\
                           .limit(2).all()
    editable_dates = [d[0].strftime("%Y-%m-%d") for d in recent_dates_query]
    
    return target_date.strftime("%Y-%m-%d") in editable_dates

# ----------------------------
# 业务接口 4：发布新作业 (包含 80% 相似度聚合逻辑)
# ----------------------------
@app.post("/api/tasks", summary="发布新作业并自动聚合")
def create_tasks(request: schemas.TaskCreateRequest, db: Session = Depends(get_db)):
    # 🌟 [核心拦截]：后端防君子也防小人，防止抓包强行发布周末作业
    if not check_is_workday(db, request.target_date):
        raise HTTPException(status_code=403, detail="日历显示该日为休息日，不允许布置作业！")

    # 1. 安全校验：限制一次最多提交 5 个任务
    if len(request.tasks) > 5:
        raise HTTPException(status_code=400, detail="一次最多只能发布 5 个任务")
    if len(request.tasks) == 0:
        raise HTTPException(status_code=400, detail="任务内容不能为空")

    # 2. 查出当天、同科目的所有已有作业，作为我们的“比对池”
    existing_tasks = db.query(models.Task).filter(
        models.Task.target_date == request.target_date,
        models.Task.subject_id == request.subject_id
    ).all()

    created_tasks_info = []

    # 3. 遍历用户提交上来的新任务，逐一进行相似度比对
    for item in request.tasks:
        best_match_group_id = None
        highest_similarity = 0.0

        # 和比对池里的老任务挨个打分
        for old_task in existing_tasks:
            # 如果老任务已经被锁定了，跳过不比对（防篡改逻辑：锁定的任务独立存在）
            if old_task.is_locked:
                continue
                
            sim_score = calculate_similarity(item.content, old_task.content)
            if sim_score > highest_similarity:
                highest_similarity = sim_score
                best_match_group_id = old_task.similarity_group_id

        # 4. 判定聚合逻辑：如果最高相似度 >= 80% (0.8)，则加入该老组；否则自立门户创建新组
        if highest_similarity >= 0.65:
            final_group_id = best_match_group_id
            status_msg = f"触发聚合 (相似度 {highest_similarity:.0%})"
        else:
            final_group_id = str(uuid.uuid4()) # 生成一个全球唯一的 ID 作为新组名
            status_msg = "自立新组"


        # 5. 组装新任务并插入数据库
        new_task = models.Task(
            subject_id=request.subject_id,
            target_date=request.target_date,
            user_id=request.user_id,
            content=item.content,
            similarity_group_id=final_group_id,
            like_count=0  # 刚发布，点赞数为 0
        )
        db.add(new_task)
        
        # 将新任务加入比对池，这样如果用户一次性提交了两个极其相似的任务，也能被正确聚合
        existing_tasks.append(new_task) 
        
        created_tasks_info.append({
            "content": item.content,
            "group_id": final_group_id,
            "status": status_msg
        })

    db.commit()

    return {
        "code": 200, 
        "message": "作业发布成功", 
        "data": created_tasks_info
    }


from sqlalchemy import desc
from collections import defaultdict

# ----------------------------
# 业务接口 5：获取作业列表 (升级：联动真实姓名)
# ----------------------------
@app.get("/api/tasks", summary="获取按相似度聚合的作业列表")
def get_tasks(
    subject_id: int,
    target_date: date,
    user_id: int,
    db: Session = Depends(get_db)
):
    # 1. 动态判断是否允许修改
    is_editable = check_is_editable(db, subject_id, target_date)

    # 2. 查询当天该科目的所有作业
    tasks = db.query(models.Task).filter(
        models.Task.subject_id == subject_id,
        models.Task.target_date == target_date
    ).all()

    # 🌟 [核心新增逻辑]：提取真实姓名 🌟
    # 先收集这批作业里所有发布者的 user_id
    publisher_ids = {task.user_id for task in tasks}
    publisher_name_map = {}
    
    if publisher_ids:
        # 利用 SQLAlchemy 进行多表联查：把 User 表和 Student 表连起来
        user_student_records = db.query(models.User, models.Student)\
                                 .join(models.Student, models.User.student_id == models.Student.id)\
                                 .filter(models.User.id.in_(publisher_ids)).all()
                                 
        for user, student in user_student_records:
            # 完美拼装："张伟" + "爸爸" = "张伟爸爸"
            publisher_name_map[user.id] = f"{student.name}{user.relation}"

    # 3. 查询当前用户对这些作业的“点赞状态”
    user_likes = db.query(models.TaskLike.task_id).filter(
        models.TaskLike.user_id == user_id
    ).all()
    liked_task_ids = {like[0] for like in user_likes} 

    # 4. 按 similarity_group_id 进行分组聚合
    groups = defaultdict(list)
    for task in tasks:
        groups[task.similarity_group_id].append(task)

    tasks_groups_response = []

    # 5. 格式化输出逻辑
    for group_id, group_tasks in groups.items():
        group_tasks.sort(key=lambda x: (-x.like_count, x.created_at))
        locked_task = next((t for t in group_tasks if t.is_locked), None)

        def format_task_dict(t):
            return {
                "id": t.id,
                "content": t.content,
                "like_count": t.like_count,
                "has_liked": t.id in liked_task_ids,
                "publisher_id": t.user_id,
                # 🌟 [核心修改]：从刚才查出的真实姓名图库里取值 🌟
                "publisher_name": publisher_name_map.get(t.user_id, f"神秘家长(ID:{t.user_id})"), 
                "created_at": t.created_at.strftime("%H:%M")
            }

        if locked_task:
            tasks_groups_response.append({
                "group_id": group_id,
                "is_locked": True,
                "highest_like_count": locked_task.like_count,
                "top_task": format_task_dict(locked_task),
                "similar_tasks": [] 
            })
        elif not is_editable:
            top_task = group_tasks[0]
            tasks_groups_response.append({
                "group_id": group_id,
                "is_locked": False, 
                "highest_like_count": top_task.like_count,
                "top_task": format_task_dict(top_task),
                "similar_tasks": [] 
            })
        else:
            top_task = group_tasks[0]
            similar_tasks = [format_task_dict(t) for t in group_tasks[1:]]
            tasks_groups_response.append({
                "group_id": group_id,
                "is_locked": False,
                "highest_like_count": top_task.like_count,
                "top_task": format_task_dict(top_task),
                "similar_tasks": similar_tasks 
            })

    tasks_groups_response.sort(key=lambda x: x["highest_like_count"], reverse=True)

    return {
        "code": 200,
        "data": {
            "current_date": target_date.strftime("%Y-%m-%d"),
            "is_editable": is_editable,
            "tasks_groups": tasks_groups_response
        }
    }
# ----------------------------
# 业务接口 6：点赞 / 取消点赞
# ----------------------------
@app.post("/api/tasks/{task_id}/like", summary="点赞或取消点赞")
def toggle_task_like(task_id: int, request: schemas.TaskLikeRequest, db: Session = Depends(get_db)):
    # 1. 检查任务是否存在
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="该作业任务不存在")
        
    # 如果任务已经被锁定，直接拒绝点赞（赛马结束）
    if task.is_locked:
        raise HTTPException(status_code=403, detail="该任务已确认锁定，无法再点赞")

    # 2. 查询当前用户是否已经对这个任务点过赞
    existing_like = db.query(models.TaskLike).filter(
        models.TaskLike.task_id == task_id,
        models.TaskLike.user_id == request.user_id
    ).first()

    if existing_like:
        # 场景 A：已经点过赞 -> 执行【取消点赞】逻辑
        db.delete(existing_like)
        # 严谨起见，防止数据异常导致负数
        task.like_count = max(0, task.like_count - 1) 
        action_msg = "取消点赞成功"
        current_has_liked = False
    else:
        # 场景 B：还没点过赞 -> 执行【点赞】逻辑
        new_like = models.TaskLike(task_id=task_id, user_id=request.user_id)
        db.add(new_like)
        task.like_count += 1
        action_msg = "点赞成功"
        current_has_liked = True

    # 提交数据库事务
    db.commit()

    # 将最新的点赞状态和数量返回给前端，前端直接拿着这个数据更新 UI，不需要刷新整个列表
    return {
        "code": 200,
        "message": action_msg,
        "data": {
            "task_id": task_id,
            "like_count": task.like_count,
            "has_liked": current_has_liked
        }
    }


# ----------------------------
# 业务接口 7：管理员密码锁定任务 (增强版：动态读取密码 + 附带清理落选任务)
# ----------------------------
@app.post("/api/tasks/{task_id}/lock", summary="输入密码锁定任务(设为最终版)")
def lock_task(task_id: int, request: schemas.TaskLockRequest, db: Session = Depends(get_db)):
    # 1. 从数据库读取配置
    config = db.query(models.ClassConfig).first()
    
    # 如果数据库里还没配置记录，自动初始化一条
    if not config:
        config = models.ClassConfig(invite_code="666666", lock_password="888888")
        db.add(config)
        db.commit()
        db.refresh(config)

    # 2. 动态校验管理密码
    if request.admin_password != config.lock_password:
        raise HTTPException(status_code=403, detail="管理密码错误，无权锁定该任务")

    # 3. 查找该任务
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="该作业任务不存在")

    if task.is_locked:
        return {"code": 200, "message": "该任务已经处于锁定状态"}

    # 4. 核心逻辑：将选中的任务设为锁定
    task.is_locked = True
    
    # 5. 暴力美学，彻底删除同分组下的其他“落选”任务！
    db.query(models.Task).filter(
        models.Task.similarity_group_id == task.similarity_group_id,
        models.Task.id != task_id
    ).delete(synchronize_session=False)

    # 提交事务
    db.commit()

    return {
        "code": 200, 
        "message": "锁定成功！落选的相似版本已自动清理。"
    }



# ----------------------------
# 业务接口 9：获取某个月份有作业的日期集合 (修复时间模块报错)
# ----------------------------
@app.get("/api/tasks/active-dates", summary="获取某月有作业的日期")
def get_active_dates(subject_id: int, year: int, month: int, db: Session = Depends(get_db)):
    # 1. 计算出这个月的第一天和最后一天
    _, last_day = calendar.monthrange(year, month)
    
    # 修复点：直接使用 datetime() 而不是 datetime.datetime()
    start_date = datetime(year, month, 1, 0, 0, 0)
    end_date = datetime(year, month, last_day, 23, 59, 59)
    
    # 2. 查询该科目在这个时间段内所有有作业的日期
    active_tasks = db.query(models.Task.target_date)\
                     .filter(
                         models.Task.subject_id == subject_id,
                         models.Task.target_date >= start_date,
                         models.Task.target_date <= end_date
                     )\
                     .distinct().all()
                     
    # 3. 提取日期部分并去重
    dates = [d[0].strftime("%Y-%m-%d") for d in active_tasks]
    
    return {"code": 200, "data": dates}

# ----------------------------
# 业务接口 10：修改自己发布的作业 (重走算法 + 扣减点赞)
# ----------------------------
@app.put("/api/tasks/{task_id}", summary="修改自己发布的作业")
def update_task(task_id: int, request: schemas.TaskUpdateRequest, db: Session = Depends(get_db)):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="该作业任务不存在")
        
    if task.user_id != request.user_id:
        raise HTTPException(status_code=403, detail="只能修改自己发布的任务哦")
        
    if task.is_locked:
        raise HTTPException(status_code=403, detail="该任务所在组已确认锁定，无法修改")

    # 1. 期限校验：应用最新的工作日与活跃期规则
    t_date = task.target_date.date() if isinstance(task.target_date, datetime) else task.target_date
    if not check_is_editable(db, task.subject_id, t_date):
        raise HTTPException(status_code=403, detail="历史归档日期的作业无法修改")

    if len(request.content.strip()) < 3:
        raise HTTPException(status_code=400, detail="内容最少需要3个字")

    new_content = request.content.strip()
    
    # 2. 核心：提取当天该科目的其他作业，重新进行相似度比对
    existing_tasks = db.query(models.Task).filter(
        models.Task.target_date == task.target_date,
        models.Task.subject_id == task.subject_id,
        models.Task.id != task_id  # 必须排除自己，否则和自己比肯定是 100%
    ).all()
    
    best_match_group_id = None
    highest_similarity = 0.0

    for old_task in existing_tasks:
        if old_task.is_locked:
            continue
        sim_score = calculate_similarity(new_content, old_task.content)
        if sim_score > highest_similarity:
            highest_similarity = sim_score
            best_match_group_id = old_task.similarity_group_id

    # 判定新的归属组
    if highest_similarity >= 0.65:
        final_group_id = best_match_group_id
    else:
        final_group_id = str(uuid.uuid4()) # 相似度太低，自立门户

    # 3. 执行数据更新
    task.content = new_content
    task.similarity_group_id = final_group_id
    
    # 4. 严谨的数据扣减：不仅减 count，还要删掉真实的 task_likes 记录
    if task.like_count > 0:
        # 优先撤销作者自己的点赞记录，如果没有则撤销该任务的任意一个点赞记录
        like_record = db.query(models.TaskLike).filter(
            models.TaskLike.task_id == task_id, 
            models.TaskLike.user_id == request.user_id
        ).first()
        
        if not like_record:
            like_record = db.query(models.TaskLike).filter(models.TaskLike.task_id == task_id).first()
            
        if like_record:
            db.delete(like_record)
            task.like_count -= 1

    db.commit()

    return {"code": 200, "message": "修改成功，已重新计算分组"}

# ----------------------------
# 业务接口 11：删除自己本设备发布的作业
# ----------------------------
@app.delete("/api/tasks/{task_id}", summary="删除自己发布的作业")
def delete_task(task_id: int, user_id: int, db: Session = Depends(get_db)):
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="该作业任务不存在")
        
    # 核心拦截：必须是当前设备绑定的 user_id 才能删除
    if task.user_id != user_id:
        raise HTTPException(status_code=403, detail="只能删除本设备发布的任务哦")
        
    # 状态拦截：锁定的不能删
    if task.is_locked:
        raise HTTPException(status_code=403, detail="该任务所在组已确认锁定，无法删除")

    # 期限拦截：应用最新的工作日与活跃期规则
    t_date = task.target_date.date() if isinstance(task.target_date, datetime) else task.target_date
    if not check_is_editable(db, task.subject_id, t_date):
        raise HTTPException(status_code=403, detail="历史归档日期的作业无法删除")

    # 1. 暴力美学：先清理掉这个任务身上的所有点赞记录，防止数据库外键报错
    db.query(models.TaskLike).filter(models.TaskLike.task_id == task_id).delete(synchronize_session=False)
    
    # 2. 彻底删除任务本身
    db.delete(task)
    db.commit()

    return {"code": 200, "message": "删除成功"}