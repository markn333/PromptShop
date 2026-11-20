"""リポジトリ・サービス層が投げる例外。HTTP の応答への変換は app.main で行う。"""


class AppError(Exception):
    """利用者に見せてよいメッセージを持つ例外の基底クラス。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    """指定された id のデータが存在しない。"""


class DuplicateNameError(AppError):
    """同じ名前のデータがすでに存在する。"""


class InvalidReferenceError(AppError):
    """参照先（ジャンル等）が存在しない。"""


class InvalidImageError(AppError):
    """画像として扱えないデータ（対応外の形式、壊れたファイル）。"""


class TooLargeError(AppError):
    """アップロードされたファイルが上限サイズを超えている。"""


class ProviderNotConfiguredError(AppError):
    """プロバイダーの API キーが設定されていない。"""


class BusyError(AppError):
    """別の変換が実行中。"""


class InvalidInputError(AppError):
    """入力された値が受け付けられない形式。"""
