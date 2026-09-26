import ctypes
from ctypes import wintypes
import os


JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
HANDLE_FLAG_INHERIT = 0x00000001
PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100


class WindowsJobError(OSError):
    pass


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE

    _kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL

    _kernel32.AssignProcessToJobObject.argtypes = (
        wintypes.HANDLE,
        wintypes.HANDLE,
    )
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

    _kernel32.OpenProcess.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    _kernel32.OpenProcess.restype = wintypes.HANDLE

    _kernel32.SetHandleInformation.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    _kernel32.SetHandleInformation.restype = wintypes.BOOL

    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
else:
    _kernel32 = None


def _last_error(operation):
    error_code = ctypes.get_last_error()
    message = ctypes.FormatError(error_code).strip()
    return WindowsJobError(
        error_code,
        f"{operation} failed: {message}",
    )


class WindowsJob:
    def __init__(self):
        if _kernel32 is None:
            raise WindowsJobError("Windows Job Objects are only available on Windows.")

        self._handle = _kernel32.CreateJobObjectW(None, None)

        if not self._handle:
            raise _last_error("CreateJobObjectW")

        try:
            if not _kernel32.SetHandleInformation(
                self._handle,
                HANDLE_FLAG_INHERIT,
                0,
            ):
                raise _last_error("SetHandleInformation")

            information = _JobObjectExtendedLimitInformation()
            information.BasicLimitInformation.LimitFlags = (
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )

            if not _kernel32.SetInformationJobObject(
                self._handle,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                ctypes.byref(information),
                ctypes.sizeof(information),
            ):
                raise _last_error("SetInformationJobObject")
        except Exception:
            _kernel32.CloseHandle(self._handle)
            self._handle = None
            raise

    def assign(self, process):
        if not self._handle:
            raise WindowsJobError("The Windows Job Object is closed.")

        process_handle = _kernel32.OpenProcess(
            PROCESS_TERMINATE | PROCESS_SET_QUOTA,
            False,
            process.pid,
        )

        if not process_handle:
            raise _last_error("OpenProcess")

        try:
            if not _kernel32.AssignProcessToJobObject(
                self._handle,
                process_handle,
            ):
                raise _last_error("AssignProcessToJobObject")
        finally:
            _kernel32.CloseHandle(process_handle)

    def close(self):
        if not self._handle:
            return

        if not _kernel32.CloseHandle(self._handle):
            raise _last_error("CloseHandle")

        self._handle = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
