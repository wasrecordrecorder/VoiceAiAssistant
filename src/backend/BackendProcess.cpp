#include "backend/BackendProcess.hpp"

#include "core/BuildInfo.hpp"
#include "core/Paths.hpp"
#include "core/Utf.hpp"

#include <bcrypt.h>

#include <array>
#include <filesystem>
#include <format>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace webviewda::backend
{
BackendProcess::BackendProcess() = default;

BackendProcess::~BackendProcess()
{
    Stop();
}

std::wstring BackendProcess::GenerateToken() const
{
    std::array<unsigned char, 32> bytes{};
    if (BCryptGenRandom(nullptr, bytes.data(), static_cast<ULONG>(bytes.size()), BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0)
    {
        throw std::runtime_error("BCryptGenRandom failed.");
    }

    std::wostringstream token;
    token << std::hex;
    for (const auto value : bytes)
    {
        token.width(2);
        token.fill(L'0');
        token << static_cast<unsigned int>(value);
    }
    return token.str();
}

std::wstring ResolveExecutable(const wchar_t* name)
{
    const DWORD length = SearchPathW(nullptr, name, nullptr, 0, nullptr, nullptr);
    if (length == 0)
    {
        return {};
    }

    std::wstring path(length, L'\0');
    const DWORD written = SearchPathW(nullptr, name, nullptr, length, path.data(), nullptr);
    if (written == 0 || written >= length)
    {
        return {};
    }
    path.resize(written);
    return path;
}

std::wstring BackendProcess::ResolvePython() const
{
    const auto backend = core::Paths::BackendDirectory();
    const auto visible = backend / L".venv" / L"Scripts" / L"python.exe";
    if (std::filesystem::exists(visible))
    {
        return visible.wstring();
    }

    if (const auto python = ResolveExecutable(L"python.exe"); !python.empty())
    {
        return python;
    }

    throw std::runtime_error("Python backend environment is missing. Run scripts/setup.ps1 first or install Python 3.11+.");
}

void BackendProcess::Start()
{
    Stop();

    try
    {
        const auto token = GenerateToken();
        const auto python = ResolvePython();
        const auto backend = core::Paths::BackendDirectory();
        const auto data = core::Paths::DataDirectory();
        std::filesystem::create_directories(data);

        std::wstring command = L"\"" + python + L"\" -m assistant_backend --host 127.0.0.1 --port " +
            std::to_wstring(core::BackendPort) + L" --token " + token + L" --data-dir \"" + data.wstring() + L"\"";
        std::vector<wchar_t> mutableCommand(command.begin(), command.end());
        mutableCommand.push_back(L'\0');

        SECURITY_ATTRIBUTES security{};
        security.nLength = sizeof(security);
        security.bInheritHandle = TRUE;

        const auto logPath = data / L"backend.log";
        const HANDLE logHandle = CreateFileW(
            logPath.c_str(),
            FILE_APPEND_DATA,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            &security,
            OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL,
            nullptr);
        if (logHandle == INVALID_HANDLE_VALUE)
        {
            throw std::runtime_error("Backend log file could not be opened.");
        }

        const HANDLE inputHandle = CreateFileW(
            L"NUL",
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            &security,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            nullptr);
        if (inputHandle == INVALID_HANDLE_VALUE)
        {
            CloseHandle(logHandle);
            throw std::runtime_error("Backend standard input could not be prepared.");
        }

        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        startup.dwFlags = STARTF_USESTDHANDLES;
        startup.hStdInput = inputHandle;
        startup.hStdOutput = logHandle;
        startup.hStdError = logHandle;

        const BOOL created = CreateProcessW(
            nullptr,
            mutableCommand.data(),
            nullptr,
            nullptr,
            TRUE,
            CREATE_NO_WINDOW,
            nullptr,
            backend.c_str(),
            &startup,
            &process_);

        CloseHandle(inputHandle);
        CloseHandle(logHandle);

        if (!created)
        {
            throw std::runtime_error("Python backend could not be started. Run backend/bootstrap.ps1 first.");
        }

        job_ = CreateJobObjectW(nullptr, nullptr);
        if (job_ == nullptr)
        {
            throw std::runtime_error("CreateJobObjectW failed.");
        }

        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if (!SetInformationJobObject(job_, JobObjectExtendedLimitInformation, &limits, sizeof(limits)) ||
            !AssignProcessToJobObject(job_, process_.hProcess))
        {
            throw std::runtime_error("Python backend job initialization failed.");
        }

        connection_.online = true;
        connection_.token = core::ToUtf8(token);
        connection_.websocketUrl = std::format("ws://127.0.0.1:{}/ws", core::BackendPort);
        connection_.error.clear();
    }
    catch (const std::exception& error)
    {
        Stop();
        connection_.online = false;
        connection_.token.clear();
        connection_.websocketUrl.clear();
        connection_.error = error.what();
    }
}

void BackendProcess::Stop()
{
    if (process_.hProcess != nullptr)
    {
        TerminateProcess(process_.hProcess, 0);
        WaitForSingleObject(process_.hProcess, 1000);
        CloseHandle(process_.hThread);
        CloseHandle(process_.hProcess);
        process_ = {};
    }

    if (job_ != nullptr)
    {
        CloseHandle(job_);
        job_ = nullptr;
    }
}

const BackendConnection& BackendProcess::Connection() const noexcept
{
    return connection_;
}
}
