#pragma once

#include "backend/BackendProcess.hpp"

#include <Windows.h>
#include <objbase.h>
#include <wrl.h>
#include <WebView2.h>

#include <nlohmann/json_fwd.hpp>

#include <string_view>

namespace webviewda::bridge
{
class Bridge final
{
public:
    Bridge(HWND window, Microsoft::WRL::ComPtr<ICoreWebView2> webView, backend::BackendConnection connection);
    ~Bridge();

    Bridge(const Bridge&) = delete;
    Bridge& operator=(const Bridge&) = delete;

    void Attach();
    void PostEvent(std::string_view event, const nlohmann::json& payload);

private:
    void Receive(ICoreWebView2WebMessageReceivedEventArgs* arguments);
    void Dispatch(std::wstring_view payload);
    void Send(std::string_view event, const nlohmann::json& payload);
    void SendError(std::string_view message);

    HWND window_;
    Microsoft::WRL::ComPtr<ICoreWebView2> webView_;
    backend::BackendConnection connection_;
    EventRegistrationToken token_{};
    bool attached_{};
};
}
