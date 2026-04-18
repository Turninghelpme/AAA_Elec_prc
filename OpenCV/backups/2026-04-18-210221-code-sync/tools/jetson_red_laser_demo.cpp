#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <csignal>
#include <cstring>
#include <cerrno>
#include <iomanip>
#include <iostream>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/videoio.hpp>

namespace {

const char* kHtmlPage = R"(<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Jetson Red Laser Demo (C++)</title>
    <style>
      body { font-family: sans-serif; background: #111; color: #eee; margin: 24px; }
      img { max-width: 100%; height: auto; border: 1px solid #444; display: block; }
      .meta { margin-top: 12px; color: #bbb; }
      code { color: #9fe8a4; }
    </style>
  </head>
  <body>
    <h1>Jetson Red Laser Demo (C++)</h1>
    <img src="/stream.mjpg" alt="stream">
    <div class="meta" id="meta">Loading status...</div>
    <script>
      async function refreshStatus() {
        try {
          const response = await fetch('/status.json');
          const status = await response.json();
          const pos = status.detected
            ? `x=${status.x}, y=${status.y}, area=${status.area}`
            : 'not found';
          document.getElementById('meta').innerHTML =
            `FPS: <code>${status.fps.toFixed(1)}</code> | ` +
            `Red laser: <code>${pos}</code> | ` +
            `Frame: <code>${status.width}x${status.height}</code>`;
        } catch (error) {
          document.getElementById('meta').textContent = 'Status fetch failed';
        }
      }
      refreshStatus();
      setInterval(refreshStatus, 250);
    </script>
  </body>
</html>
)";

struct Args {
  std::string device = "/dev/video0";
  std::string host = "0.0.0.0";
  int port = 8091;
  int width = 640;
  int height = 480;
  int fps = 30;
  int quality = 80;
  int score_threshold = 120;
  int min_red = 150;
  int min_delta = 40;
  int min_area = 3;
  int max_area = 400;
  int morph_kernel = 3;
};

struct Detection {
  bool found = false;
  int x = 0;
  int y = 0;
  int area = 0;
};

struct Status {
  bool detected = false;
  int x = -1;
  int y = -1;
  int area = 0;
  double fps = 0.0;
  int width = 0;
  int height = 0;
  double timestamp = 0.0;
};

struct FramePacket {
  std::vector<uchar> jpeg;
  Status status;
  std::uint64_t frame_id = 0;
};

std::atomic<bool> g_running{true};

std::string jsonEscape(const std::string& input) {
  std::string output;
  output.reserve(input.size());
  for (char ch : input) {
    if (ch == '"' || ch == '\\') {
      output.push_back('\\');
    }
    output.push_back(ch);
  }
  return output;
}

std::string makeStatusJson(const Status& status) {
  std::ostringstream oss;
  oss << std::fixed << std::setprecision(6);
  oss << "{";
  oss << "\"detected\":" << (status.detected ? "true" : "false") << ",";
  if (status.detected) {
    oss << "\"x\":" << status.x << ",";
    oss << "\"y\":" << status.y << ",";
  } else {
    oss << "\"x\":null,";
    oss << "\"y\":null,";
  }
  oss << "\"area\":" << status.area << ",";
  oss << "\"fps\":" << status.fps << ",";
  oss << "\"width\":" << status.width << ",";
  oss << "\"height\":" << status.height << ",";
  oss << "\"timestamp\":" << status.timestamp;
  oss << "}";
  return oss.str();
}

bool sendAll(int fd, const void* data, std::size_t length) {
  const char* ptr = static_cast<const char*>(data);
  std::size_t sent = 0;
  while (sent < length) {
    ssize_t result = ::send(fd, ptr + sent, length - sent, 0);
    if (result <= 0) {
      return false;
    }
    sent += static_cast<std::size_t>(result);
  }
  return true;
}

bool sendTextResponse(int fd,
                      const std::string& status_line,
                      const std::string& content_type,
                      const std::string& body,
                      bool head_only) {
  std::ostringstream oss;
  oss << "HTTP/1.0 " << status_line << "\r\n";
  oss << "Content-Type: " << content_type << "\r\n";
  oss << "Content-Length: " << body.size() << "\r\n";
  oss << "Connection: close\r\n\r\n";
  const std::string headers = oss.str();
  if (!sendAll(fd, headers.data(), headers.size())) {
    return false;
  }
  if (!head_only && !body.empty()) {
    return sendAll(fd, body.data(), body.size());
  }
  return true;
}

bool sendBinaryResponse(int fd,
                        const std::string& status_line,
                        const std::string& content_type,
                        const std::vector<uchar>& body,
                        bool head_only) {
  std::ostringstream oss;
  oss << "HTTP/1.0 " << status_line << "\r\n";
  oss << "Content-Type: " << content_type << "\r\n";
  oss << "Content-Length: " << body.size() << "\r\n";
  oss << "Connection: close\r\n\r\n";
  const std::string headers = oss.str();
  if (!sendAll(fd, headers.data(), headers.size())) {
    return false;
  }
  if (!head_only && !body.empty()) {
    return sendAll(fd, body.data(), body.size());
  }
  return true;
}

Args parseArgs(int argc, char** argv) {
  Args args;
  for (int i = 1; i < argc; ++i) {
    std::string key = argv[i];
    auto nextValue = [&](const std::string& name) -> std::string {
      if (i + 1 >= argc) {
        throw std::runtime_error("Missing value for " + name);
      }
      return argv[++i];
    };

    if (key == "--device") {
      args.device = nextValue(key);
    } else if (key == "--host") {
      args.host = nextValue(key);
    } else if (key == "--port") {
      args.port = std::stoi(nextValue(key));
    } else if (key == "--width") {
      args.width = std::stoi(nextValue(key));
    } else if (key == "--height") {
      args.height = std::stoi(nextValue(key));
    } else if (key == "--fps") {
      args.fps = std::stoi(nextValue(key));
    } else if (key == "--quality") {
      args.quality = std::stoi(nextValue(key));
    } else if (key == "--score-threshold") {
      args.score_threshold = std::stoi(nextValue(key));
    } else if (key == "--min-red") {
      args.min_red = std::stoi(nextValue(key));
    } else if (key == "--min-delta") {
      args.min_delta = std::stoi(nextValue(key));
    } else if (key == "--min-area") {
      args.min_area = std::stoi(nextValue(key));
    } else if (key == "--max-area") {
      args.max_area = std::stoi(nextValue(key));
    } else if (key == "--morph-kernel") {
      args.morph_kernel = std::stoi(nextValue(key));
    } else {
      throw std::runtime_error("Unknown argument: " + key);
    }
  }
  return args;
}

class RedLaserTracker {
 public:
  explicit RedLaserTracker(const Args& args)
      : args_(args),
        encode_params_{cv::IMWRITE_JPEG_QUALITY, args_.quality},
        status_{false, -1, -1, 0, 0.0, args_.width, args_.height, nowSeconds()} {
    cv::setUseOptimized(true);

    capture_.open(args_.device, cv::CAP_V4L2);
    if (!capture_.isOpened()) {
      throw std::runtime_error("Failed to open camera device: " + args_.device);
    }

    capture_.set(cv::CAP_PROP_FOURCC, cv::VideoWriter::fourcc('M', 'J', 'P', 'G'));
    capture_.set(cv::CAP_PROP_FRAME_WIDTH, args_.width);
    capture_.set(cv::CAP_PROP_FRAME_HEIGHT, args_.height);
    capture_.set(cv::CAP_PROP_FPS, args_.fps);
    capture_.set(cv::CAP_PROP_BUFFERSIZE, 1);

    worker_ = std::thread(&RedLaserTracker::run, this);
  }

  ~RedLaserTracker() {
    stop();
  }

  void stop() {
    bool expected = true;
    if (running_.compare_exchange_strong(expected, false)) {
      frame_cv_.notify_all();
      if (worker_.joinable()) {
        worker_.join();
      }
      capture_.release();
    }
  }

  FramePacket getLatest() const {
    std::lock_guard<std::mutex> lock(frame_mutex_);
    return FramePacket{jpeg_frame_, status_, frame_id_};
  }

  FramePacket waitForNext(std::uint64_t last_frame_id, int timeout_ms) const {
    std::unique_lock<std::mutex> lock(frame_mutex_);
    frame_cv_.wait_for(lock, std::chrono::milliseconds(timeout_ms), [&] {
      return frame_id_ > last_frame_id || !running_.load();
    });
    return FramePacket{jpeg_frame_, status_, frame_id_};
  }

  bool isRunning() const {
    return running_.load();
  }

 private:
  static double nowSeconds() {
    const auto now = std::chrono::system_clock::now();
    const auto epoch = now.time_since_epoch();
    return std::chrono::duration<double>(epoch).count();
  }

  Detection detect(const cv::Mat& frame) const {
    const Detection roi_detection = detectInRect(frame, currentRoi(frame));
    if (roi_detection.found) {
      return roi_detection;
    }
    return detectInRect(frame, cv::Rect(0, 0, frame.cols, frame.rows));
  }

  void overlay(cv::Mat& frame, const Detection& detection, double fps) const {
    cv::putText(frame,
                "FPS: " + formatOneDecimal(fps),
                cv::Point(12, 28),
                cv::FONT_HERSHEY_SIMPLEX,
                0.7,
                cv::Scalar(0, 255, 255),
                2,
                cv::LINE_AA);

    if (detection.found) {
      cv::circle(frame, cv::Point(detection.x, detection.y), 10, cv::Scalar(0, 255, 255), 2);
      cv::line(frame,
               cv::Point(detection.x - 15, detection.y),
               cv::Point(detection.x + 15, detection.y),
               cv::Scalar(0, 255, 255),
               1);
      cv::line(frame,
               cv::Point(detection.x, detection.y - 15),
               cv::Point(detection.x, detection.y + 15),
               cv::Scalar(0, 255, 255),
               1);

      cv::putText(frame,
                  "RED: (" + std::to_string(detection.x) + ", " +
                      std::to_string(detection.y) + ") area=" + std::to_string(detection.area),
                  cv::Point(12, 58),
                  cv::FONT_HERSHEY_SIMPLEX,
                  0.65,
                  cv::Scalar(0, 255, 0),
                  2,
                  cv::LINE_AA);
    } else {
      cv::putText(frame,
                  "RED: not found",
                  cv::Point(12, 58),
                  cv::FONT_HERSHEY_SIMPLEX,
                  0.65,
                  cv::Scalar(0, 0, 255),
                  2,
                  cv::LINE_AA);
    }

    cv::rectangle(frame,
                  cv::Rect(0, 0, std::max(1, frame.cols - 1), std::max(1, frame.rows - 1)),
                  cv::Scalar(80, 80, 80),
                  1);
  }

  static std::string formatOneDecimal(double value) {
    std::ostringstream oss;
    oss << std::fixed << std::setprecision(1) << value;
    return oss.str();
  }

  void run() {
    using clock = std::chrono::steady_clock;
    auto last_time = clock::now();
    double fps = 0.0;

    while (running_.load()) {
      cv::Mat frame;
      if (!capture_.read(frame) || frame.empty()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
        continue;
      }

      const auto now = clock::now();
      const double delta =
          std::max(1e-6, std::chrono::duration<double>(now - last_time).count());
      const double current_fps = 1.0 / delta;
      fps = (fps == 0.0) ? current_fps : (0.9 * fps + 0.1 * current_fps);
      last_time = now;

      Detection detection = detect(frame);
      if (detection.found) {
        has_last_detection_ = true;
        last_detection_ = detection;
      } else {
        has_last_detection_ = false;
      }
      overlay(frame, detection, fps);

      std::vector<uchar> encoded;
      if (!cv::imencode(".jpg", frame, encoded, encode_params_)) {
        continue;
      }

      Status status;
      status.detected = detection.found;
      status.x = detection.found ? detection.x : -1;
      status.y = detection.found ? detection.y : -1;
      status.area = detection.found ? detection.area : 0;
      status.fps = fps;
      status.width = frame.cols;
      status.height = frame.rows;
      status.timestamp = nowSeconds();

      {
        std::lock_guard<std::mutex> lock(frame_mutex_);
        jpeg_frame_.swap(encoded);
        status_ = status;
        ++frame_id_;
      }
      frame_cv_.notify_all();
    }
  }

  Args args_;
  cv::Rect currentRoi(const cv::Mat& frame) const {
    if (!has_last_detection_) {
      return cv::Rect(0, 0, frame.cols, frame.rows);
    }

    constexpr int kRoiRadius = 96;
    const int x0 = std::max(0, last_detection_.x - kRoiRadius);
    const int y0 = std::max(0, last_detection_.y - kRoiRadius);
    const int x1 = std::min(frame.cols, last_detection_.x + kRoiRadius + 1);
    const int y1 = std::min(frame.rows, last_detection_.y + kRoiRadius + 1);
    return cv::Rect(x0, y0, std::max(1, x1 - x0), std::max(1, y1 - y0));
  }

  Detection detectInRect(const cv::Mat& frame, const cv::Rect& rect) const {
    Detection detection;
    int best_score = std::numeric_limits<int>::min();
    int best_x = -1;
    int best_y = -1;

    for (int y = rect.y; y < rect.y + rect.height; ++y) {
      const cv::Vec3b* src = frame.ptr<cv::Vec3b>(y);
      for (int x = rect.x; x < rect.x + rect.width; ++x) {
        const int blue = src[x][0];
        const int green = src[x][1];
        const int red = src[x][2];
        const int score = (2 * red) - green - blue;
        if (score < args_.score_threshold ||
            red < args_.min_red ||
            (red - green) < args_.min_delta ||
            (red - blue) < args_.min_delta) {
          continue;
        }

        if (score > best_score) {
          best_score = score;
          best_x = x;
          best_y = y;
        }
      }
    }

    if (best_x < 0 || best_y < 0) {
      return detection;
    }

    constexpr int kClusterRadius = 8;
    int area = 0;
    long sum_x = 0;
    long sum_y = 0;
    const int x0 = std::max(0, best_x - kClusterRadius);
    const int y0 = std::max(0, best_y - kClusterRadius);
    const int x1 = std::min(frame.cols, best_x + kClusterRadius + 1);
    const int y1 = std::min(frame.rows, best_y + kClusterRadius + 1);

    for (int y = y0; y < y1; ++y) {
      const cv::Vec3b* src = frame.ptr<cv::Vec3b>(y);
      for (int x = x0; x < x1; ++x) {
        const int blue = src[x][0];
        const int green = src[x][1];
        const int red = src[x][2];
        const int score = (2 * red) - green - blue;
        if (score < args_.score_threshold ||
            red < args_.min_red ||
            (red - green) < args_.min_delta ||
            (red - blue) < args_.min_delta) {
          continue;
        }

        ++area;
        sum_x += x;
        sum_y += y;
      }
    }

    if (area < args_.min_area || area > args_.max_area) {
      return detection;
    }

    detection.found = true;
    detection.area = area;
    detection.x = static_cast<int>(std::lround(static_cast<double>(sum_x) / area));
    detection.y = static_cast<int>(std::lround(static_cast<double>(sum_y) / area));
    return detection;
  }

  mutable bool has_last_detection_ = false;
  mutable Detection last_detection_;
  std::vector<int> encode_params_;
  mutable std::mutex frame_mutex_;
  mutable std::condition_variable frame_cv_;
  std::vector<uchar> jpeg_frame_;
  Status status_;
  std::uint64_t frame_id_ = 0;
  std::atomic<bool> running_{true};
  cv::VideoCapture capture_;
  std::thread worker_;
};

class HttpServer {
 public:
  HttpServer(const Args& args, RedLaserTracker& tracker) : args_(args), tracker_(tracker) {}

  void run() {
    int server_fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) {
      throw std::runtime_error("Failed to create socket");
    }

    int opt = 1;
    ::setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(static_cast<uint16_t>(args_.port));
    if (args_.host == "0.0.0.0") {
      addr.sin_addr.s_addr = INADDR_ANY;
    } else {
      if (::inet_pton(AF_INET, args_.host.c_str(), &addr.sin_addr) <= 0) {
        ::close(server_fd);
        throw std::runtime_error("Invalid host address: " + args_.host);
      }
    }

    if (::bind(server_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
      ::close(server_fd);
      throw std::runtime_error("Failed to bind socket");
    }
    if (::listen(server_fd, 8) < 0) {
      ::close(server_fd);
      throw std::runtime_error("Failed to listen on socket");
    }

    while (g_running.load() && tracker_.isRunning()) {
      sockaddr_in client_addr{};
      socklen_t client_len = sizeof(client_addr);
      const int client_fd =
          ::accept(server_fd, reinterpret_cast<sockaddr*>(&client_addr), &client_len);
      if (client_fd < 0) {
        if (errno == EINTR) {
          continue;
        }
        break;
      }

      std::thread(&HttpServer::handleClient, this, client_fd).detach();
    }

    ::close(server_fd);
  }

 private:
  struct Request {
    std::string method;
    std::string path;
  };

  static bool parseRequest(int fd, Request& request) {
    std::string raw;
    raw.reserve(4096);
    char buffer[1024];

    while (raw.find("\r\n\r\n") == std::string::npos && raw.size() < 8192) {
      const ssize_t received = ::recv(fd, buffer, sizeof(buffer), 0);
      if (received <= 0) {
        return false;
      }
      raw.append(buffer, buffer + received);
    }

    std::istringstream iss(raw);
    iss >> request.method >> request.path;
    return !request.method.empty() && !request.path.empty();
  }

  void handleClient(int client_fd) {
    Request request;
    if (!parseRequest(client_fd, request)) {
      ::close(client_fd);
      return;
    }

    const bool head_only = (request.method == "HEAD");
    if (request.method != "GET" && request.method != "HEAD") {
      sendTextResponse(client_fd,
                       "405 Method Not Allowed",
                       "text/plain; charset=utf-8",
                       "Method Not Allowed",
                       head_only);
      ::close(client_fd);
      return;
    }

    if (request.path == "/" || request.path == "/index.html") {
      sendTextResponse(client_fd,
                       "200 OK",
                       "text/html; charset=utf-8",
                       kHtmlPage,
                       head_only);
      ::close(client_fd);
      return;
    }

    if (request.path == "/status.json") {
      const std::string body = makeStatusJson(tracker_.getLatest().status);
      sendTextResponse(client_fd,
                       "200 OK",
                       "application/json; charset=utf-8",
                       body,
                       head_only);
      ::close(client_fd);
      return;
    }

    if (request.path == "/snapshot.jpg") {
      const FramePacket packet = tracker_.getLatest();
      if (packet.jpeg.empty()) {
        sendTextResponse(client_fd,
                         "503 Service Unavailable",
                         "text/plain; charset=utf-8",
                         "No frame available",
                         head_only);
      } else {
        sendBinaryResponse(client_fd, "200 OK", "image/jpeg", packet.jpeg, head_only);
      }
      ::close(client_fd);
      return;
    }

    if (request.path == "/stream.mjpg") {
      handleStream(client_fd, head_only);
      ::close(client_fd);
      return;
    }

    sendTextResponse(client_fd,
                     "404 Not Found",
                     "text/plain; charset=utf-8",
                     "Not Found",
                     head_only);
    ::close(client_fd);
  }

  void handleStream(int client_fd, bool head_only) {
    std::ostringstream oss;
    oss << "HTTP/1.0 200 OK\r\n";
    oss << "Age: 0\r\n";
    oss << "Cache-Control: no-cache, private\r\n";
    oss << "Pragma: no-cache\r\n";
    oss << "Content-Type: multipart/x-mixed-replace; boundary=FRAME\r\n";
    oss << "Connection: close\r\n\r\n";
    const std::string headers = oss.str();
    if (!sendAll(client_fd, headers.data(), headers.size()) || head_only) {
      return;
    }

    std::uint64_t last_frame_id = 0;
    while (g_running.load() && tracker_.isRunning()) {
      const FramePacket packet = tracker_.waitForNext(last_frame_id, 1000);
      if (packet.frame_id == 0 || packet.jpeg.empty()) {
        continue;
      }
      last_frame_id = packet.frame_id;

      std::ostringstream part;
      part << "--FRAME\r\n";
      part << "Content-Type: image/jpeg\r\n";
      part << "Content-Length: " << packet.jpeg.size() << "\r\n\r\n";
      const std::string part_header = part.str();
      if (!sendAll(client_fd, part_header.data(), part_header.size())) {
        return;
      }
      if (!sendAll(client_fd, packet.jpeg.data(), packet.jpeg.size())) {
        return;
      }
      if (!sendAll(client_fd, "\r\n", 2)) {
        return;
      }
    }
  }

  Args args_;
  RedLaserTracker& tracker_;
};

void signalHandler(int) {
  g_running.store(false);
}

}  // namespace

int main(int argc, char** argv) {
  try {
    std::signal(SIGINT, signalHandler);
    std::signal(SIGTERM, signalHandler);
    std::signal(SIGPIPE, SIG_IGN);

    const Args args = parseArgs(argc, argv);
    RedLaserTracker tracker(args);
    HttpServer server(args, tracker);

    char hostname[256] = {0};
    if (::gethostname(hostname, sizeof(hostname) - 1) != 0) {
      std::strncpy(hostname, "localhost", sizeof(hostname) - 1);
    }

    std::cout << "Red laser C++ demo ready on http://" << hostname << ":" << args.port << "/"
              << std::endl;
    std::cout << "Red laser C++ demo ready on http://127.0.0.1:" << args.port << "/"
              << std::endl;

    server.run();
    tracker.stop();
    return 0;
  } catch (const std::exception& ex) {
    std::cerr << "ERROR: " << ex.what() << std::endl;
    return 1;
  }
}
