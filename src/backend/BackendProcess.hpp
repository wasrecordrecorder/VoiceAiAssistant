#pragma once

#include <Windows.h>

#include <string>

namespace webviewda::backend
{
struct BackendConnection final
{
    bool online{};
    std::string websocketUrl;
    std::string token;
    std::string error;
};

class BackendProcess final
{
public:
    BackendProcess();
    ~BackendProcess();

    BackendProcess(const BackendProcess&) = delete;
    BackendProcess& operator=(const BackendProcess&) = delete;

    void Start();
    void Stop();
    const BackendConnection& Connection() const noexcept;

private:
    std::wstring GenerateToken() const;
    std::wstring ResolvePython() const;

    PROCESS_INFORMATION process_{};
    HANDLE job_{};
    BackendConnection connection_{};
};
}
