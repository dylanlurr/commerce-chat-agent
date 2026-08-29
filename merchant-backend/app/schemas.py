from pydantic import BaseModel, Field


class ProductOut(BaseModel):
    sku: str
    name: str
    description: str
    price: float
    currency: str
    stock: int

    class Config:
        from_attributes = True


class UploadResult(BaseModel):
    uploaded: int = Field(ge=0)
