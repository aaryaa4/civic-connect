import shutil
from typing import List, Optional
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Depends, HTTPException, status, Request, Form, File, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import JWTError, jwt

import models
from database import SessionLocal, engine, get_db

# --- INITIAL SETUP ---
models.Base.metadata.create_all(bind=engine)
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
templates = Jinja2Templates(directory="templates")

# --- SECURE ADMIN CREATION ON STARTUP ---
@app.on_event("startup")
def create_super_user():
    db = SessionLocal()
    ADMIN_EMAIL = "admin@gov.in"
    ADMIN_PASSWORD = "AdminPassword123!"
    admin = get_user_by_email(db, email=ADMIN_EMAIL)
    if not admin:
        default_community = db.query(models.Community).filter(models.Community.id == 1).first()
        if not default_community:
            db_community = models.Community(id=1, name="Downtown", city="Pimpri-Chinchwad")
            db.add(db_community)
            db.commit()
            db.refresh(db_community)
        admin_user = models.User(
            email=ADMIN_EMAIL,
            hashed_password=get_password_hash(ADMIN_PASSWORD),
            full_name="Municipal Admin",
            role=models.UserRole.admin,
            community_id=1,
            is_active=True
        )
        db.add(admin_user)
        db.commit()
        print("Admin user created successfully.")
    db.close()

# --- SECURITY & AUTHENTICATION ---
SECRET_KEY = "your_super_secret_key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password): return pwd_context.verify(plain_password, hashed_password)
def get_password_hash(password): return pwd_context.hash(password)
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# --- PYDANTIC SCHEMAS ---
class UserCreate(BaseModel): email: EmailStr; full_name: str; password: str; community_id: int = 1
class TokenData(BaseModel): email: Optional[str] = None
class Report(BaseModel):
    id: int; caption: str; image_url: str; latitude: float; longitude: float
    category: models.ReportCategory; status: models.ReportStatus; timestamp: datetime; owner_id: int
    class Config: from_attributes = True

# --- CRUD OPERATIONS ---
def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()

def create_user(db: Session, user: UserCreate):
    hashed_password = get_password_hash(user.password)
    db_user = models.User(email=user.email, hashed_password=hashed_password, full_name=user.full_name, community_id=user.community_id, role=models.UserRole.user)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# --- HTML PAGE ENDPOINTS ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request): return templates.TemplateResponse("index.html", {"request": request})
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request): return templates.TemplateResponse("login.html", {"request": request})
@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request): return templates.TemplateResponse("register.html", {"request": request})
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request): return templates.TemplateResponse("user_dashboard.html", {"request": request})
@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request): return templates.TemplateResponse("admin_dashboard.html", {"request": request})

# --- API ENDPOINTS ---
@app.post("/token")
async def login_for_access_token(db: Session = Depends(get_db), email: str = Form(), password: str = Form(), user_type: str = Form()):
    user = get_user_by_email(db, email=email)
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    if user_type == "admin" and user.role != models.UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied. Not an admin.")
    access_token = create_access_token(data={"sub": user.email, "role": user.role.value})
    return {"access_token": access_token, "token_type": "bearer", "user_role": user.role.value}

@app.post("/register")
async def register_user(request: Request, email: str = Form(), full_name: str = Form(), password: str = Form(), db: Session = Depends(get_db)):
    if email == "admin@gov.in":
        return templates.TemplateResponse("register.html", {"request": request, "error": "This email is reserved."})
    db_user = get_user_by_email(db, email=email)
    if db_user:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Email already registered"})
    user_data = UserCreate(email=email, full_name=full_name, password=password)
    create_user(db=db, user=user_data)
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

def get_current_user_from_token(token: str, db: Session):
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None: raise credentials_exception
    except JWTError: raise credentials_exception
    user = get_user_by_email(db, email=email)
    if user is None: raise credentials_exception
    return user

@app.post("/api/reports")
async def create_report(token: str = Form(), caption: str = Form(), latitude: float = Form(), longitude: float = Form(), category: str = Form(), is_emergency: bool = Form(False), file: UploadFile = File(...), db: Session = Depends(get_db)):
    current_user = get_current_user_from_token(token, db)
    safe_filename = f"{int(datetime.now().timestamp())}_{file.filename.replace('..', '')}"
    file_location = f"uploads/{safe_filename}"
    with open(file_location, "wb+") as file_object: shutil.copyfileobj(file.file, file_object)
    db_report = models.Report(caption=caption, latitude=latitude, longitude=longitude, category=category, is_emergency=is_emergency, image_url=file_location, owner_id=current_user.id, community_id=current_user.community_id)
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    return db_report

@app.get("/api/reports", response_model=List[Report])
async def get_reports(token: str, db: Session = Depends(get_db)):
    user = get_current_user_from_token(token, db)
    if user.role == models.UserRole.admin:
        return db.query(models.Report).order_by(models.Report.timestamp.desc()).all()
    else:
        return db.query(models.Report).filter(models.Report.owner_id == user.id).order_by(models.Report.timestamp.desc()).all()

@app.post("/api/reports/{report_id}/status")
async def update_report_status(report_id: int, new_status: models.ReportStatus = Form(...), token: str = Form(...), db: Session = Depends(get_db)):
    user = get_current_user_from_token(token, db)
    if user.role != models.UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can update status.")
    db_report = db.query(models.Report).filter(models.Report.id == report_id).first()
    if not db_report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    db_report.status = new_status
    db.commit()
    return {"message": "Status updated successfully", "new_status": new_status.value}

@app.post("/api/reports/{report_id}/feedback")
async def submit_feedback(report_id: int, rating: int = Form(...), comment: str = Form(None), token: str = Form(...), db: Session = Depends(get_db)):
    user = get_current_user_from_token(token, db)
    db_report = db.query(models.Report).filter(models.Report.id == report_id).first()

    if not db_report or db_report.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only give feedback on your own reports.")
    if db_report.status != models.ReportStatus.resolved:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot give feedback until report is resolved.")
    
    existing_feedback = db.query(models.Feedback).filter(models.Feedback.report_id == report_id).first()
    if existing_feedback:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Feedback has already been submitted for this report.")
        
    db_feedback = models.Feedback(rating=rating, comment=comment, report_id=report_id, owner_id=user.id)
    db.add(db_feedback)
    db.commit()
    return {"message": "Feedback submitted successfully."}
