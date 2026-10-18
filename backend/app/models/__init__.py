from .acquisition import *
from .gallery import *
from .face_cases import *
from .people import *
from .system import *
from .tasks import *
from .videos import *
from .provenance import *

from app.db import Base
from app.schema_comments import apply_schema_comments


apply_schema_comments(Base.metadata)
