cmake_minimum_required(VERSION 3.26)

project(WebViewDA VERSION 0.19.0 LANGUAGES CXX)

if(NOT WIN32)
    message(FATAL_ERROR "WebViewDA targets Windows because it uses Microsoft Edge WebView2.")
endif()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)

set(WEBVIEW2_VERSION "1.0.3967.48" CACHE STRING "Microsoft.Web.WebView2 SDK version")

FetchContent_Declare(
    webview2
    URL "https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/${WEBVIEW2_VERSION}"
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)

FetchContent_Declare(
    nlohmann_json
    URL "https://github.com/nlohmann/json/releases/download/v3.12.0/json.tar.xz"
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)

FetchContent_MakeAvailable(webview2 nlohmann_json)

include(cmake/WebView2.cmake)

configure_file(src/core/BuildInfo.hpp.in "${CMAKE_CURRENT_BINARY_DIR}/generated/core/BuildInfo.hpp" @ONLY)

add_executable(
    WebViewDA
    WIN32
    src/main.cpp
    src/app/Application.cpp
    src/app/Application.hpp
    src/backend/BackendProcess.cpp
    src/backend/BackendProcess.hpp
    src/bridge/Bridge.cpp
    src/bridge/Bridge.hpp
    src/core/BuildInfo.hpp.in
    src/core/Paths.cpp
    src/core/Paths.hpp
    src/core/Result.hpp
    src/core/Utf.cpp
    src/core/Utf.hpp
    src/platform/windows/ComApartment.cpp
    src/platform/windows/ComApartment.hpp
    src/platform/windows/TrayIcon.cpp
    src/platform/windows/TrayIcon.hpp
    src/platform/windows/AppMessages.hpp
    src/platform/windows/PushToTalk.cpp
    src/platform/windows/PushToTalk.hpp
    src/platform/windows/OverlayWindow.cpp
    src/platform/windows/OverlayWindow.hpp
    src/platform/windows/Window.cpp
    src/platform/windows/Window.hpp
    src/webview/WebViewHost.cpp
    src/webview/WebViewHost.hpp
)

target_include_directories(
    WebViewDA
    PRIVATE
    src
    "${CMAKE_CURRENT_BINARY_DIR}/generated"
    "${WEBVIEW2_INCLUDE_DIR}"
)

target_compile_definitions(
    WebViewDA
    PRIVATE
    UNICODE
    _UNICODE
    NOMINMAX
    WIN32_LEAN_AND_MEAN
    $<$<CONFIG:Debug>:WEBVIEWDA_DEBUG>
)

target_compile_options(WebViewDA PRIVATE /W4 /permissive- /utf-8 /Zc:__cplusplus /EHsc)

target_link_libraries(
    WebViewDA
    PRIVATE
    WebView2Loader
    nlohmann_json::nlohmann_json
    bcrypt
    dwmapi
    gdi32
    ole32
    shell32
    shlwapi
    user32
)

set_target_properties(
    WebViewDA
    PROPERTIES
    OUTPUT_NAME "WebViewDA"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    VS_DEBUGGER_WORKING_DIRECTORY "$<TARGET_FILE_DIR:WebViewDA>"
)

foreach(config Debug Release RelWithDebInfo MinSizeRel)
    string(TOUPPER "${config}" config_upper)
    set_target_properties(WebViewDA PROPERTIES RUNTIME_OUTPUT_DIRECTORY_${config_upper} "${CMAKE_BINARY_DIR}/bin/${config}")
endforeach()

add_custom_command(
    TARGET WebViewDA
    POST_BUILD
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different "$<TARGET_FILE:WebView2Loader>" "$<TARGET_FILE_DIR:WebViewDA>"
    COMMAND "${CMAKE_COMMAND}" -E copy_directory "${CMAKE_CURRENT_SOURCE_DIR}/assets" "$<TARGET_FILE_DIR:WebViewDA>/assets"
    COMMAND "${CMAKE_COMMAND}" -E copy_directory "${CMAKE_CURRENT_SOURCE_DIR}/backend" "$<TARGET_FILE_DIR:WebViewDA>/backend"
)
