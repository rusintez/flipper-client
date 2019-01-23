from typing import Iterator, Optional, cast

from .interface import AbstractFeatureFlagStore, FlagDoesNotExistError
from .storage import FeatureFlagStoreItem, FeatureFlagStoreMeta
from .util.date import now


class S3FeatureFlagStore(AbstractFeatureFlagStore):
    def __init__(
        self, client, bucket_name: str, page_size: Optional[int] = 1000
    ) -> None:
        self._client = client
        self._bucket_name = bucket_name
        self._page_size = page_size

    def create(
        self,
        feature_name: str,
        is_enabled: bool = False,
        client_data: Optional[dict] = None,
    ) -> FeatureFlagStoreItem:
        item = FeatureFlagStoreItem(
            feature_name, is_enabled, FeatureFlagStoreMeta(now(), client_data)
        )
        return self._save(item)

    def _save(self, item: FeatureFlagStoreItem):
        self._client.put_object(
            Bucket=self._bucket_name, Key=item.feature_name, Body=item.serialize()
        )
        return item

    def get(self, feature_name: str) -> Optional[FeatureFlagStoreItem]:
        try:
            response = self._client.get_object(
                Bucket=self._bucket_name, Key=feature_name
            )
        except self._client.exceptions.NoSuchKey:
            return None
        serialized = response["Body"].read()
        return FeatureFlagStoreItem.deserialize(serialized)

    def set(self, feature_name: str, is_enabled: bool):
        existing = self.get(feature_name)

        if existing is None:
            self.create(feature_name, is_enabled)
            return

        item = FeatureFlagStoreItem(
            feature_name, is_enabled, FeatureFlagStoreMeta.from_dict(existing.meta)
        )

        self._save(item)

    def list(
        self, limit: Optional[int] = None, offset: int = 0
    ) -> Iterator[FeatureFlagStoreItem]:
        visited = 0

        for key in self._list_object_keys():
            visited += 1

            if visited <= offset:
                continue
            if limit is not None and visited > limit + offset:
                return

            yield cast(FeatureFlagStoreItem, self.get(key))

    def _list_object_keys(self) -> Iterator[str]:
        paginator = self._client.get_paginator("list_objects_v2")

        for page in paginator.paginate(Bucket=self._bucket_name):
            for content in page.get("Contents", []):
                yield content["Key"]

    def set_meta(self, feature_name: str, meta: FeatureFlagStoreMeta) -> None:
        existing = self.get(feature_name)

        if existing is None:
            raise FlagDoesNotExistError("Feature %s does not exist" % feature_name)

        item = FeatureFlagStoreItem(feature_name, existing.raw_is_enabled, meta)

        self._save(item)

    def delete(self, feature_name: str) -> None:
        self._client.delete_object(Bucket=self._bucket_name, Key=feature_name)