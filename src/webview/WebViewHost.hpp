#pragma once

#include "backend/BackendProcess.hpp"

#include <Windows.h>
#include <objbase.h>
#include <wrl.h>
#include <WebView2.h>

#include <memory>
#include <string>
#include <string_view>
#include <nlohmann/json_fwd.hpp>

namespace webviewda::bridge
{
class Bridge;
}

namespace webviewda::webview
{
class WebViewHost final : public std::enable_shared_from_this<WebViewHost>
{
public:
    WebViewHost(HWND parent, backend::BackendConnection connection, std::wstring page = L"index.html");
    ~WebViewHost();

    WebViewHost(const WebViewHost&) = delete;
    WebViewHost& operator=(const WebViewHost&) = delete;

    void Initialize();
    void Resize();
    void PostEvent(std::string_view event, const nlohmann::json& payload);

private:
    void EnvironmentCreated(HRESULT result, ICoreWebView2Environment* environment);
    void ControllerCreated(HRESULT result, ICoreWebView2Controller* controller);
    void Configure();
    void ShowFailure(const std::wstring& message) const;

    HWND parent_;
    backend::BackendConnection connection_;
    std::wstring page_;
    Microsoft::WRL::ComPtr<ICoreWebView2Environment> environment_;
    Microsoft::WRL::ComPtr<ICoreWebView2Controller> controller_;
    Microsoft::WRL::ComPtr<ICoreWebView2> webView_;
    std::unique_ptr<bridge::Bridge> bridge_;
};
}
