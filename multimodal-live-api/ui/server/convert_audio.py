from pydub import AudioSegment
import os

input_file = "test_audio.wav"
output_file = "test_audio_converted.wav"


def convert_audio():
    # Load the audio file
    audio = AudioSegment.from_wav(input_file)

    # Convert to mono if stereo
    if audio.channels > 1:
        audio = audio.set_channels(1)

    # Convert sample rate to 16kHz
    audio = audio.set_frame_rate(16000)

    # Export the converted file
    audio.export(output_file, format="wav")

    print(f"Converted {input_file} to mono, 16kHz and saved as {output_file}")
    print(f"Original file size: {os.path.getsize(input_file) / 1024:.2f}KB")
    print(f"Converted file size: {os.path.getsize(output_file) / 1024:.2f}KB")


if __name__ == "__main__":
    convert_audio()
