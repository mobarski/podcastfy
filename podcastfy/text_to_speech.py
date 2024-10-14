"""
Text-to-Speech Module

This module provides functionality to convert text into speech using various TTS models.
It supports both ElevenLabs and OpenAI TTS services and handles the conversion process,
including cleaning of input text and merging of audio files.
"""

import logging
from elevenlabs import client as elevenlabs_client
from google.cloud import texttospeech
from pydub import AudioSegment
import io
import os
import re
import random
import openai
from typing import List, Tuple, Optional, Union
try:
	from .utils.config import load_config
except ImportError:
	from utils.config import load_config

logger = logging.getLogger(__name__)


class TextToSpeech:
	def __init__(self, model: str = 'openai', api_key: Optional[str] = None):
		"""
		Initialize the TextToSpeech class.

		Args:
			model (str): The model to use for text-to-speech conversion. 
						 Options are 'elevenlabs' or 'openai'. Defaults to 'openai'.
			api_key (Optional[str]): API key for the selected text-to-speech service.
						   If not provided, it will be loaded from the config.
		"""
		self.model = model.lower()
		self.config = load_config()
		self.tts_config = self.config.get('text_to_speech')

		if self.model == 'elevenlabs':
			self.api_key = api_key or self.config.ELEVENLABS_API_KEY
			self.client = elevenlabs_client.ElevenLabs(api_key=self.api_key)
		elif self.model == 'openai':
			self.api_key = api_key or self.config.OPENAI_API_KEY
			openai.api_key = self.api_key
		elif self.model == 'google':
			# GOOGLE_APPLICATION_CREDENTIALS environment variable
			# must be set with the path to the service account JSON file.
			# REF: https://cloud.google.com/docs/authentication/application-default-credentials
			self.client = texttospeech.TextToSpeechClient()
		else:
			raise ValueError("Invalid model. Choose 'elevenlabs', 'openai' or 'google'.")

		self.audio_format = self.tts_config['audio_format']
		self.temp_audio_dir = self.tts_config['temp_audio_dir']
		self.ending_message = self.tts_config['ending_message']

		# Create temp_audio_dir if it doesn't exist
		if not os.path.exists(self.temp_audio_dir):
			os.makedirs(self.temp_audio_dir)

	def __merge_audio_files(self, input_dir: str, output_file: str) -> None:
		"""
		Merge all audio files in the input directory sequentially and save the result.

		Args:
			input_dir (str): Path to the directory containing audio files.
			output_file (str): Path to save the merged audio file.
		"""
		try:
			# Function to sort filenames naturally
			def natural_sort_key(filename: str) -> List[Union[int, str]]:
				return [int(text) if text.isdigit() else text for text in re.split(r'(\d+)', filename)]
			
			combined = AudioSegment.empty()
			audio_files = sorted(
				[f for f in os.listdir(input_dir) if f.endswith(f".{self.audio_format}")],
				key=natural_sort_key
			)
			for file in audio_files:
				if file.endswith(f".{self.audio_format}"):
					file_path = os.path.join(input_dir, file)
					combined += AudioSegment.from_file(file_path, format=self.audio_format)
			
			combined.export(output_file, format=self.audio_format)
			logger.info(f"Merged audio saved to {output_file}")
		except Exception as e:
			logger.error(f"Error merging audio files: {str(e)}")
			raise

	def convert_to_speech(self, text: str, output_file: str) -> None:
		"""
		Convert input text to speech and save as an audio file.

		Args:
			text (str): Input text to convert to speech.
			output_file (str): Path to save the output audio file.

		Raises:
			Exception: If there's an error in converting text to speech.
		"""
		# Clean TSS markup tags from the input text
		cleaned_text = self.clean_tss_markup(text)

		if self.model == 'elevenlabs':
			self.__convert_to_speech_elevenlabs(cleaned_text, output_file)
		elif self.model == 'openai':
			self.__convert_to_speech_openai(cleaned_text, output_file)
		elif self.model == 'google':
			self.__convert_to_speech_google(cleaned_text, output_file)

	def __convert_to_speech_elevenlabs(self, text: str, output_file: str) -> None:
		try:
			qa_pairs = self.split_qa(text)
			audio_files = []
			counter = 0
			for question, answer in qa_pairs:
				question_audio = self.client.generate(
					text=question,
					voice=self.tts_config['elevenlabs']['default_voices']['question'],
					model=self.tts_config['elevenlabs']['model']
				)
				answer_audio = self.client.generate(
					text=answer,
					voice=self.tts_config['elevenlabs']['default_voices']['answer'],
					model=self.tts_config['elevenlabs']['model']
				)

				# Save question and answer audio chunks
				for audio in [question_audio, answer_audio]:
					counter += 1
					file_name = f"{self.temp_audio_dir}{counter}.{self.audio_format}"
					with open(file_name, "wb") as out:
						for chunk in audio:
							if chunk:
								out.write(chunk)
					audio_files.append(file_name)

			# Merge all audio files and save the result
			self.__merge_audio_files(self.temp_audio_dir, output_file)

			# Clean up individual audio files
			for file in audio_files:
				os.remove(file)
			
			logger.info(f"Audio saved to {output_file}")

		except Exception as e:
			logger.error(f"Error converting text to speech with ElevenLabs: {str(e)}")
			raise

	def __convert_to_speech_openai(self, text: str, output_file: str) -> None:
		try:
			qa_pairs = self.split_qa(text)
			print(qa_pairs)
			audio_files = []
			counter = 0
			for question, answer in qa_pairs:
				for speaker, content in [
					(self.tts_config['openai']['default_voices']['question'], question),
					(self.tts_config['openai']['default_voices']['answer'], answer)
				]:
					counter += 1
					file_name = f"{self.temp_audio_dir}{counter}.{self.audio_format}"
					response = openai.audio.speech.create(
						model=self.tts_config['openai']['model'],
						voice=speaker,
						input=content
					)
					with open(file_name, "wb") as file:
						file.write(response.content)

					audio_files.append(file_name)

			# Merge all audio files and save the result
			self.__merge_audio_files(self.temp_audio_dir, output_file)

			# Clean up individual audio files
			for file in audio_files:
				os.remove(file)
			
			logger.info(f"Audio saved to {output_file}")

		except Exception as e:
			logger.error(f"Error converting text to speech with OpenAI: {str(e)}")
			raise

	def __convert_to_speech_google(self, text: str, output_file: str) -> None:
		try:
			qa_pairs = self.split_qa(text)

			combined_q = AudioSegment.empty()
			combined_a = AudioSegment.empty()
			tts_config = self.tts_config['google']

			# configure the voices
			question_voice = texttospeech.VoiceSelectionParams(
				language_code=tts_config.get('language_code', 'en-US'),
				name=tts_config['default_voices']['question']['voice'],
			)
			answer_voice = texttospeech.VoiceSelectionParams(
				language_code=tts_config.get('language_code', 'en-US'),
				name=tts_config['default_voices']['answer']['voice'],
			)
			last_overlap_duration = 0.0
			for question, answer in qa_pairs:
				for kind, content, speaker in [
					('question', question, question_voice),
					('answer', answer, answer_voice),
				]:
					voice_config = tts_config['default_voices'][kind]
					
					# configure the audio output
					config_kwargs = dict(
						audio_encoding=texttospeech.AudioEncoding.OGG_OPUS,
						speaking_rate=voice_config.get('rate'),
						pitch=voice_config.get('pitch'),
					)
					# apply random variation to speaking_rate and pitch
					if config_kwargs['speaking_rate']:
						config_kwargs['speaking_rate'] *= random.uniform(0.95, 1.2)  # TODO: make this configurable
					if config_kwargs['pitch']:
						config_kwargs['pitch'] += random.uniform(-2, 2)	 # TODO: make this configurable
					# remove None values from config_kwargs (required by some voices)
					audio_config = texttospeech.AudioConfig(
						**{k: v for k, v in config_kwargs.items() if v is not None}
					)

					# configure the synthesis input
					use_text_input = 'Journey' in voice_config['voice']  # UGLY
					synth_input_type = 'text' if use_text_input else 'ssml'
					synth_input = texttospeech.SynthesisInput(**{synth_input_type: content})
					
					# get audio content from the TTS service
					response = self.client.synthesize_speech(
						input=synth_input,
						voice=speaker,
						audio_config=audio_config,
					)

					# generate silent audio segment for the other speaker
					overlap_duration = random.uniform(0.2, 0.4)  # TODO: make this configurable
					audio_segment = AudioSegment.from_file(io.BytesIO(response.audio_content), format='ogg')
					duration_seconds = audio_segment.duration_seconds
					silence_duration = duration_seconds - overlap_duration - last_overlap_duration
					last_overlap_duration = overlap_duration
					silence = AudioSegment.silent(duration=silence_duration * 1000)
					
					# add audio segments to each speaker
					if kind == 'question':
						combined_q += audio_segment
						combined_a += silence
					else:
						combined_q += silence
						combined_a += audio_segment
			
			# add silence for the last overlap
			combined_q += AudioSegment.silent(duration=last_overlap_duration * 1000)

			# export speaker audio segments to separate files
			combined_q.export(output_file.replace('.mp3', '_question.mp3'), format=self.audio_format)
			combined_a.export(output_file.replace('.mp3', '_answer.mp3'), format=self.audio_format)
			# merge speaker audio segments and save the result
			combined_q.overlay(combined_a).export(output_file, format=self.audio_format)

			logger.info(f"Audio saved to {output_file}")

		except Exception as e:
			logger.error(f"Error converting text to speech with OpenAI: {str(e)}")
			raise

	def split_qa(self, input_text: str) -> List[Tuple[str, str]]:
		"""
		Split the input text into question-answer pairs.

		Args:
			input_text (str): The input text containing Person1 and Person2 dialogues.

		Returns:
			List[Tuple[str, str]]: A list of tuples containing (Person1, Person2) dialogues.
		"""
		# Add ending message to the end of input_text
		input_text += f"<Person2>{self.ending_message}</Person2>"

		# Regular expression pattern to match Person1 and Person2 dialogues
		pattern = r'<Person1>(.*?)</Person1>\s*<Person2>(.*?)</Person2>'
		
		# Find all matches in the input text
		matches = re.findall(pattern, input_text, re.DOTALL)
		
		# Process the matches to remove extra whitespace and newlines
		processed_matches = [
			(
				' '.join(person1.split()).strip(),
				' '.join(person2.split()).strip()
			)
			for person1, person2 in matches
		]
		return processed_matches

	def clean_tss_markup(self, input_text: str, additional_tags: List[str] = ["Person1", "Person2"]) -> str:
		"""
		Remove unsupported TSS markup tags from the input text while preserving supported SSML tags.

		Args:
			input_text (str): The input text containing TSS markup tags.
			additional_tags (List[str]): Optional list of additional tags to preserve. Defaults to ["Person1", "Person2"].

		Returns:
			str: Cleaned text with unsupported TSS markup tags removed.
		"""
		# List of SSML tags supported by both OpenAI and ElevenLabs
		supported_tags = [
			'speak', 'break', 'lang', 'p', 'phoneme',
			's', 'say-as', 'sub'
		]

		# Append additional tags to the supported tags list
		supported_tags.extend(additional_tags)

		# Create a pattern that matches any tag not in the supported list
		pattern = r'</?(?!(?:' + '|'.join(supported_tags) + r')\b)[^>]+>'

		# Remove unsupported tags
		cleaned_text = re.sub(pattern, '', input_text)

		# Remove any leftover empty lines
		cleaned_text = re.sub(r'\n\s*\n', '\n', cleaned_text)

		# Ensure closing tags for additional tags are preserved
		for tag in additional_tags:
			cleaned_text = re.sub(f'<{tag}>(.*?)(?=<(?:{"|".join(additional_tags)})>|$)', 
								  f'<{tag}>\\1</{tag}>', 
								  cleaned_text, 
								  flags=re.DOTALL)

		return cleaned_text.strip()


def main(seed: int = 42) -> None:
	"""
	Main function to test the TextToSpeech class.

	Args:
		seed (int): Random seed for reproducibility. Defaults to 42.
	"""
	try:
		# Read input text from file
		transcript_path = 'tests/data/transcript_336aa9f955cd4019bc1287379a5a2820.txt'
		with open(transcript_path, 'r') as file:
			input_text = file.read()
		
		# generate audio for each model
		for model in ['elevenlabs', 'openai', 'google']:
			tts = TextToSpeech(model=model)
			output_file = f'tests/data/response_{model}.mp3'
			tts.convert_to_speech(input_text, output_file)
			logger.info(f"{model.capitalize()} TTS completed. Output saved to {output_file}")

	except Exception as e:
		logger.error(f"An error occurred during text-to-speech conversion: {str(e)}")
		raise


if __name__ == "__main__":
	main(seed=42)
