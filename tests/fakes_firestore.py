"""
Fake in-memory Firestore client + fake S3 client para tests.

No es un archivo de tests (no sigue el patrón test_*.py), así que pytest
no lo recolecta como módulo de pruebas; solo se importa desde otros tests.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional


def _match(actual: Any, op: str, expected: Any) -> bool:
    if op == "==":
        return actual == expected
    raise NotImplementedError(f"Operador no soportado en FakeFirestore: {op}")


class FakeDocumentSnapshot:
    def __init__(self, doc_id: str, data: Optional[dict]):
        self.id = doc_id
        self.exists = data is not None
        self._data = data

    def to_dict(self) -> Optional[dict]:
        return dict(self._data) if self._data is not None else None


class FakeDocumentRef:
    def __init__(self, collection: "FakeCollection", doc_id: str):
        self._collection = collection
        self.id = doc_id

    def get(self) -> FakeDocumentSnapshot:
        return FakeDocumentSnapshot(self.id, self._collection._docs.get(self.id))

    def set(self, data: dict) -> None:
        self._collection._docs[self.id] = dict(data)

    def update(self, data: dict) -> None:
        existing = self._collection._docs.setdefault(self.id, {})
        existing.update(data)

    def delete(self) -> None:
        self._collection._docs.pop(self.id, None)


class FakeQuery:
    def __init__(
        self,
        collection: "FakeCollection",
        filters=None,
        order_field: Optional[str] = None,
        order_desc: bool = False,
        limit_n: Optional[int] = None,
    ):
        self._collection = collection
        self._filters = filters or []
        self._order_field = order_field
        self._order_desc = order_desc
        self._limit = limit_n

    def where(self, field: str, op: str, value: Any) -> "FakeQuery":
        return FakeQuery(
            self._collection,
            filters=self._filters + [(field, op, value)],
            order_field=self._order_field,
            order_desc=self._order_desc,
            limit_n=self._limit,
        )

    def order_by(self, field: str, direction: str = "ASCENDING") -> "FakeQuery":
        return FakeQuery(
            self._collection,
            filters=self._filters,
            order_field=field,
            order_desc=(direction == "DESCENDING"),
            limit_n=self._limit,
        )

    def limit(self, n: int) -> "FakeQuery":
        return FakeQuery(
            self._collection,
            filters=self._filters,
            order_field=self._order_field,
            order_desc=self._order_desc,
            limit_n=n,
        )

    def _resolve(self):
        items = list(self._collection._docs.items())
        for field, op, value in self._filters:
            items = [(k, v) for k, v in items if _match(v.get(field), op, value)]
        if self._order_field:
            items.sort(key=lambda kv: kv[1].get(self._order_field), reverse=self._order_desc)
        if self._limit is not None:
            items = items[: self._limit]
        return items

    def stream(self):
        return [FakeDocumentSnapshot(k, v) for k, v in self._resolve()]

    def get(self):
        return self.stream()


class FakeAggregationResult:
    def __init__(self, value: int, alias: str = "count"):
        self.value = value
        self.alias = alias


class FakeAggregationQuery:
    def __init__(self, collection: "FakeCollection"):
        self._collection = collection

    def get(self):
        return [[FakeAggregationResult(len(self._collection._docs))]]


class FakeCollection:
    def __init__(self, name: str):
        self.name = name
        self._docs: dict[str, dict] = {}

    def document(self, doc_id: Optional[str] = None) -> FakeDocumentRef:
        if doc_id is None:
            doc_id = uuid.uuid4().hex
        return FakeDocumentRef(self, doc_id)

    def where(self, field: str, op: str, value: Any) -> FakeQuery:
        return FakeQuery(self).where(field, op, value)

    def order_by(self, field: str, direction: str = "ASCENDING") -> FakeQuery:
        return FakeQuery(self).order_by(field, direction)

    def limit(self, n: int) -> FakeQuery:
        return FakeQuery(self).limit(n)

    def stream(self):
        return FakeQuery(self).stream()

    def get(self):
        return self.stream()

    def count(self) -> FakeAggregationQuery:
        return FakeAggregationQuery(self)


class FakeFirestore:
    """Sustituto mínimo de google.cloud.firestore.Client para tests."""

    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}

    def collection(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection(name)
        return self._collections[name]


class FakeS3Client:
    """Sustituto mínimo de boto3 S3 client: registra put_object/delete_objects
    y simula list_objects_v2/generate_presigned_url sobre un inventario en
    memoria (``objects``).
    """

    def __init__(
        self,
        fail_on_upload: bool = False,
        fail_on_delete: bool = False,
        fail_on_list: bool = False,
        objects: Optional[list] = None,
    ):
        self.uploaded: list[dict] = []
        self.deleted: list[str] = []
        self.fail_on_upload = fail_on_upload
        self.fail_on_delete = fail_on_delete
        self.fail_on_list = fail_on_list
        self._objects: list[dict] = list(objects) if objects else []

    def put_object(self, Bucket: str, Key: str, Body: bytes, ContentType: str = None, **kwargs):
        if self.fail_on_upload:
            raise RuntimeError("Fallo simulado de S3 en put_object")
        self.uploaded.append({
            "Bucket": Bucket,
            "Key": Key,
            "Body": Body,
            "ContentType": ContentType,
            **kwargs,
        })
        self._objects.append({"Key": Key, "Size": len(Body) if hasattr(Body, "__len__") else 0})
        return {"ETag": "fake-etag"}

    def delete_objects(self, Bucket: str, Delete: dict, **kwargs):
        if self.fail_on_delete:
            raise RuntimeError("Fallo simulado de S3 en delete_objects")
        keys = [obj["Key"] for obj in Delete.get("Objects", [])]
        self.deleted.extend(keys)
        self._objects = [o for o in self._objects if o["Key"] not in keys]
        return {"Deleted": [{"Key": k} for k in keys]}

    def list_objects_v2(self, Bucket: str, Prefix: str = "", **kwargs):
        if self.fail_on_list:
            raise RuntimeError("Fallo simulado de S3 en list_objects_v2")
        contents = [o for o in self._objects if o["Key"].startswith(Prefix)]
        return {"Contents": contents} if contents else {}

    def generate_presigned_url(self, ClientMethod: str, Params: dict, ExpiresIn: int = 3600, **kwargs):
        bucket = Params.get("Bucket")
        key = Params.get("Key")
        return f"https://{bucket}.s3.amazonaws.com/{key}?presigned=true&expires={ExpiresIn}"
