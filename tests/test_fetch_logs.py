from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import fetch_logs


class TestBuildLogsCommand:
    def test_builds_logs_command(self):
        cmd = fetch_logs.build_logs_command("railway", "bot", 500, "@level:error", None)
        assert cmd == ["railway", "logs", "--service", "bot", "--lines", "500", "--filter", "@level:error"]

    def test_uses_since_without_lines(self):
        cmd = fetch_logs.build_logs_command("railway", "bot", 500, None, "1h")
        assert cmd == ["railway", "logs", "--service", "bot", "--since", "1h"]


class TestFetchLogs:
    def test_retries_without_service_using_rebuilt_command(self):
        first = MagicMock(returncode=1, stderr="service not found", stdout="")
        second = MagicMock(returncode=0, stderr="", stdout="ok")
        workdir = Path("C:/temp/talkguru")

        with patch("scripts.fetch_logs.subprocess.run", side_effect=[first, second]) as mock_run, \
             patch("builtins.print"):
            result = fetch_logs.fetch_logs(
                "railway",
                "token",
                workdir,
                "bot",
                500,
                "bot",
                None,
            )

        assert result == "ok"
        assert mock_run.call_args_list[0].args[0] == [
            "railway", "logs", "--service", "bot", "--lines", "500", "--filter", "bot",
        ]
        assert mock_run.call_args_list[1].args[0] == [
            "railway", "logs", "--lines", "500", "--filter", "bot",
        ]
        assert mock_run.call_args_list[0].kwargs["cwd"] == workdir
        assert mock_run.call_args_list[1].kwargs["cwd"] == workdir


class TestFetchLogsMain:
    def test_uses_isolated_temp_dir_for_project_link(self, tmp_path):
        temp_dir = MagicMock()
        temp_dir.name = str(tmp_path / "railway-context")

        log_dir = tmp_path / "logs"

        with patch("scripts.fetch_logs.check_railway_cli", return_value="railway"), \
             patch("scripts.fetch_logs.get_railway_token", return_value="token"), \
             patch("scripts.fetch_logs.link_project", return_value=True) as mock_link, \
             patch("scripts.fetch_logs.fetch_logs", return_value="line 1\n") as mock_fetch, \
             patch("scripts.fetch_logs.TemporaryDirectory", return_value=temp_dir), \
             patch("scripts.fetch_logs.os.getenv", side_effect=lambda key, default=None: {
                 "RAILWAY_PROJECT_ID": "project-123",
                 "RAILWAY_SERVICE_NAME": "bot",
             }.get(key, default)), \
             patch("scripts.fetch_logs.LOGS_DIR", log_dir), \
             patch("scripts.fetch_logs.print_summary"), \
             patch("builtins.print"), \
             patch(
                 "scripts.fetch_logs.argparse.ArgumentParser.parse_args",
                 return_value=Namespace(lines=500, all=False, since=None, filter=None, output=None),
             ):
            fetch_logs.main()

        expected_workdir = Path(temp_dir.name)
        mock_link.assert_called_once_with("railway", "project-123", "token", expected_workdir)
        mock_fetch.assert_called_once_with("railway", "token", expected_workdir, "bot", 500, None, None)
        temp_dir.cleanup.assert_called_once()
