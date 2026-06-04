#include "webview/WebViewHost.hpp"

#include "bridge/Bridge.hpp"
#include "core/BuildInfo.hpp"
#include "core/Paths.hpp"
#include "core/Result.hpp"
#include "core/Utf.hpp"

#include <filesystem>
#include <stdexcept>
#include <utility>

namespace webviewda::webview
{
using Microsoft::WRL::Callback;
using Microsoft::WRL::ComPtr;

WebViewHost::WebViewHost(HWND parent, backend::BackendConnection connection, std::wstring page) : parent_(parent), connection_(std::move(connection)), page_(std::move(page))
{
}

WebViewHost::~WebViewHost()
{
    bridge_.reset();

    if (controller_)
    {
        controller_->Close();
    }
}

void WebViewHost::Initialize()
{
    LPWSTR runtimeVersion = nullptr;
    const HRESULT runtimeResult = GetAvailableCoreWebView2BrowserVersionString(nullptr, &runtimeVersion);
    if (runtimeVersion != nullptr)
    {
        CoTaskMemFree(runtimeVersion);
    }

    core::Ensure(runtimeResult, "GetAvailableCoreWebView2BrowserVersionString");

    const auto userData = core::Paths::UserDataDirectory();
    std::filesystem::create_directories(userData);

    const std::weak_ptr<WebViewHost> weak = shared_from_this();
    const HRESULT result = CreateCoreWebView2EnvironmentWithOptions(
        nullptr,
        userData.c_str(),
        nullptr,
        Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
            [weak](HRESULT creationResult, ICoreWebView2Environment* environment) -> HRESULT
            {
                if (const auto self = weak.lock())
                {
                    self->EnvironmentCreated(creationResult, environment);
                }
                return S_OK;
            })
            .Get());

    core::Ensure(result, "CreateCoreWebView2EnvironmentWithOptions");
}

void WebViewHost::EnvironmentCreated(HRESULT result, ICoreWebView2Environment* environment)
{
    try
    {
        core::Ensure(result, "WebView2 environment creation");
        if (environment == nullptr)
        {
            throw std::runtime_error("WebView2 environment is unavailable.");
        }

        environment_ = environment;
        const std::weak_ptr<WebViewHost> weak = shared_from_this();
        const HRESULT controllerResult = environment_->CreateCoreWebView2Controller(
            parent_,
            Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                [weak](HRESULT creationResult, ICoreWebView2Controller* controller) -> HRESULT
                {
                    if (const auto self = weak.lock())
                    {
                        self->ControllerCreated(creationResult, controller);
                    }
                    return S_OK;
                })
                .Get());

        core::Ensure(controllerResult, "CreateCoreWebView2Controller");
    }
    catch (const std::exception& error)
    {
        ShowFailure(core::FromUtf8(error.what()));
    }
}

void WebViewHost::ControllerCreated(HRESULT result, ICoreWebView2Controller* controller)
{
    try
    {
        core::Ensure(result, "WebView2 controller creation");
        if (controller == nullptr)
        {
            throw std::runtime_error("WebView2 controller is unavailable.");
        }

        controller_ = controller;
        core::Ensure(controller_->get_CoreWebView2(webView_.GetAddressOf()), "get_CoreWebView2");
        Configure();
        Resize();
    }
    catch (const std::exception& error)
    {
        ShowFailure(core::FromUtf8(error.what()));
    }
}

void WebViewHost::Configure()
{
    const auto assets = core::Paths::AssetsDirectory();
    if (!std::filesystem::exists(assets / page_))
    {
        throw std::runtime_error("UI assets were not found next to the executable.");
    }

    ComPtr<ICoreWebView2Settings> settings;
    core::Ensure(webView_->get_Settings(settings.GetAddressOf()), "get_Settings");
    core::Ensure(settings->put_IsScriptEnabled(TRUE), "put_IsScriptEnabled");
    core::Ensure(settings->put_IsWebMessageEnabled(TRUE), "put_IsWebMessageEnabled");
    core::Ensure(settings->put_AreDefaultScriptDialogsEnabled(FALSE), "put_AreDefaultScriptDialogsEnabled");
    core::Ensure(settings->put_AreDefaultContextMenusEnabled(FALSE), "put_AreDefaultContextMenusEnabled");

#ifdef WEBVIEWDA_DEBUG
    core::Ensure(settings->put_AreDevToolsEnabled(TRUE), "put_AreDevToolsEnabled");
#else
    core::Ensure(settings->put_AreDevToolsEnabled(FALSE), "put_AreDevToolsEnabled");
#endif

    ComPtr<ICoreWebView2_3> advanced;
    core::Ensure(webView_.As(&advanced), "ICoreWebView2_3");
    core::Ensure(
        advanced->SetVirtualHostNameToFolderMapping(
            L"app.local",
            assets.c_str(),
            COREWEBVIEW2_HOST_RESOURCE_ACCESS_KIND_DENY_CORS),
        "SetVirtualHostNameToFolderMapping");

    EventRegistrationToken navigationToken{};
    core::Ensure(
        webView_->add_NavigationStarting(
            Callback<ICoreWebView2NavigationStartingEventHandler>(
                [](ICoreWebView2*, ICoreWebView2NavigationStartingEventArgs* arguments) -> HRESULT
                {
                    LPWSTR uriValue = nullptr;
                    if (FAILED(arguments->get_Uri(&uriValue)) || uriValue == nullptr)
                    {
                        arguments->put_Cancel(TRUE);
                        return S_OK;
                    }

                    const std::wstring uri(uriValue);
                    CoTaskMemFree(uriValue);
                    if (!uri.starts_with(L"https://app.local/"))
                    {
                        arguments->put_Cancel(TRUE);
                    }
                    return S_OK;
                })
                .Get(),
            &navigationToken),
        "add_NavigationStarting");

    bridge_ = std::make_unique<bridge::Bridge>(parent_, webView_, connection_);
    bridge_->Attach();

    const std::wstring uri = L"https://app.local/" + page_;
    core::Ensure(webView_->Navigate(uri.c_str()), "Navigate");
}

void WebViewHost::PostEvent(std::string_view event, const nlohmann::json& payload)
{
    if (bridge_)
    {
        bridge_->PostEvent(event, payload);
    }
}

void WebViewHost::Resize()
{
    if (!controller_)
    {
        return;
    }

    RECT bounds{};
    GetClientRect(parent_, &bounds);
    controller_->put_Bounds(bounds);
}

void WebViewHost::ShowFailure(const std::wstring& message) const
{
    MessageBoxW(parent_, message.c_str(), core::ProductNameWide.data(), MB_OK | MB_ICONERROR);
}
}
