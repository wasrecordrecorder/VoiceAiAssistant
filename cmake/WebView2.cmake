if(CMAKE_GENERATOR_PLATFORM MATCHES "^[Aa][Rr][Mm]64$" OR CMAKE_SYSTEM_PROCESSOR MATCHES "^(ARM64|arm64|aarch64)$")
    set(WEBVIEW2_ARCH "arm64")
elseif(CMAKE_SIZEOF_VOID_P EQUAL 8)
    set(WEBVIEW2_ARCH "x64")
else()
    set(WEBVIEW2_ARCH "x86")
endif()

set(WEBVIEW2_NATIVE_DIR "${webview2_SOURCE_DIR}/build/native")
set(WEBVIEW2_INCLUDE_DIR "${WEBVIEW2_NATIVE_DIR}/include")
set(WEBVIEW2_LOADER_DIR "${WEBVIEW2_NATIVE_DIR}/${WEBVIEW2_ARCH}")

if(NOT EXISTS "${WEBVIEW2_INCLUDE_DIR}/WebView2.h")
    message(FATAL_ERROR "WebView2 headers were not found in ${WEBVIEW2_INCLUDE_DIR}.")
endif()

if(NOT EXISTS "${WEBVIEW2_LOADER_DIR}/WebView2Loader.dll.lib")
    message(FATAL_ERROR "WebView2Loader import library was not found for ${WEBVIEW2_ARCH}.")
endif()

add_library(WebView2Loader SHARED IMPORTED GLOBAL)

set_target_properties(
    WebView2Loader
    PROPERTIES
    IMPORTED_IMPLIB "${WEBVIEW2_LOADER_DIR}/WebView2Loader.dll.lib"
    IMPORTED_LOCATION "${WEBVIEW2_LOADER_DIR}/WebView2Loader.dll"
)
