/*
 *  Copyright (c) 2011 The WebRTC project authors. All Rights Reserved.
 *
 *  Use of this source code is governed by a BSD-style license
 *  that can be found in the LICENSE file in the root of the source
 *  tree. An additional intellectual property rights grant can be found
 *  in the file PATENTS.  All contributing project authors may
 *  be found in the AUTHORS file in the root of the source tree.
 */

#include "../../../../engine_configurations.h"
#include "frame_buffer.h"
#include "packet.h"

#include <cassert>
#include <string.h>

#if defined(_WIN32)
    // VS 2005: Don't warn for default initialized arrays. See help for more info.
    #pragma warning(disable:4351)
#endif

namespace webrtc {

// Constructor
VCMFrameBuffer::VCMFrameBuffer() :
    _state(kStateFree),
    _frameCounted(false),
    _nackCount(0),
    _latestPacketTimeMs(-1)
{
}

// Destructor
VCMFrameBuffer::~VCMFrameBuffer()
{
    Reset();
}

VCMFrameBuffer::VCMFrameBuffer(VCMFrameBuffer& rhs)
:
VCMEncodedFrame(rhs),
_state(rhs._state),
_frameCounted(rhs._frameCounted),
_sessionInfo(),
_nackCount(rhs._nackCount),
_latestPacketTimeMs(rhs._latestPacketTimeMs)
{
    _sessionInfo = rhs._sessionInfo;
}

webrtc::FrameType
VCMFrameBuffer::FrameType() const
{
    return _sessionInfo.FrameType();
}

void
VCMFrameBuffer::SetPreviousFrameLoss()
{
    _sessionInfo.SetPreviousFrameLoss();
}

WebRtc_Word32
VCMFrameBuffer::GetLowSeqNum()
{
    return _sessionInfo.GetLowSeqNum();
}

WebRtc_Word32
VCMFrameBuffer::GetHighSeqNum()
{
    return _sessionInfo.GetHighSeqNum();
}

bool
VCMFrameBuffer::IsSessionComplete()
{
    return _sessionInfo.IsSessionComplete();
}

// Insert packet
VCMFrameBufferEnum
VCMFrameBuffer::InsertPacket(const VCMPacket& packet, WebRtc_Word64 timeInMs)
{
    if (_state == kStateDecoding)
    {
        // Do not insert packet
        return kIncomplete;
    }

    // Sanity to check if the frame has been freed. (Too old for example)
    if (_state == kStateFree)
    {
        return kStateError;
    }

    // is this packet part of this frame
    if (TimeStamp() && (TimeStamp() != packet.timestamp))
    {
        return kTimeStampError;
    }

    // sanity checks
    if (_size + packet.sizeBytes +
        (packet.insertStartCode ?  kH264StartCodeLengthBytes : 0 )
        > kMaxJBFrameSizeBytes)
    {
        return kSizeError;
    }
    if (NULL == packet.dataPtr && packet.sizeBytes > 0)
    {
        return kSizeError;
    }
    if ((packet.frameType != kFrameEmpty) &&
        (!_sessionInfo.HaveStartSeqNumber()))
    {
        _sessionInfo.SetStartSeqNumber(packet.seqNum);
    }
    if (packet.dataPtr != NULL)
    {
        _payloadType = packet.payloadType;
    }

    if (kStateEmpty == _state)
    {
        // First packet (empty and/or media) inserted into this frame.
        // store some info and set some initial values.
        _timeStamp = packet.timestamp;
        _codec = packet.codec;
        if (packet.frameType != kFrameEmpty)
        {
            // first media packet
            SetState(kStateIncomplete);
        }
    }

    WebRtc_UWord32 requiredSizeBytes = Length() + packet.sizeBytes +
                   (packet.insertStartCode ? kH264StartCodeLengthBytes : 0);
    if (requiredSizeBytes >= _size)
    {
        const WebRtc_UWord32 increments = requiredSizeBytes /
                                          kBufferIncStepSizeBytes +
                                        (requiredSizeBytes %
                                         kBufferIncStepSizeBytes > 0);
        const WebRtc_UWord32 newSize = _size +
                                       increments * kBufferIncStepSizeBytes;
        if (newSize > kMaxJBFrameSizeBytes)
        {
            return kSizeError;
        }
        if (VerifyAndAllocate(newSize) == -1)
        {
            return kSizeError;
        }
    }
    WebRtc_Word64 retVal = _sessionInfo.InsertPacket(packet, _buffer);
    if (retVal == -1)
    {
        return kSizeError;
    }
    else if (retVal == -2)
    {
        return kDuplicatePacket;
    }
    // update length
    _length = Length() + static_cast<WebRtc_UWord32>(retVal);

    _latestPacketTimeMs = timeInMs;

    if (_sessionInfo.IsSessionComplete())
    {
        return kCompleteSession;
    }
    else
    {
        // this layer is not complete
        if (_state == kStateComplete)
        {
            // we already have a complete layer
            // wait for all independent layers belonging to the same frame
            _state = kStateIncomplete;
        }
    }
    return kIncomplete;
}

WebRtc_Word64
VCMFrameBuffer::LatestPacketTimeMs()
{
    return _latestPacketTimeMs;
}

// Zero out all entries in list up to and including the (first)
// entry equal to _lowSeqNum
WebRtc_Word32
VCMFrameBuffer::ZeroOutSeqNum(WebRtc_Word32* list, WebRtc_Word32 num)
{
    if (_sessionInfo.ZeroOutSeqNum(list, num) != 0)
    {
       return -1;
    }
    return 0;
}

// Zero out all entries in list up to and including the (first) entry equal to
// _lowSeqNum. Hybrid mode: 1. Don't NACK FEC packets 2. Make a smart decision
// on whether to NACK or not

WebRtc_Word32
VCMFrameBuffer::ZeroOutSeqNumHybrid(WebRtc_Word32* list,
                                    WebRtc_Word32 num,
                                    float rttScore)
{
    return _sessionInfo.ZeroOutSeqNumHybrid(list, num, rttScore);
}

void
VCMFrameBuffer::IncrementNackCount()
{
    _nackCount++;
}

WebRtc_Word16
VCMFrameBuffer::GetNackCount() const
{
    return _nackCount;
}

bool
VCMFrameBuffer::HaveLastPacket()
{
    return _sessionInfo.HaveLastPacket();
}

bool
VCMFrameBuffer::ForceSetHaveLastPacket()
{
    _sessionInfo.ForceSetHaveLastPacket();
    return _sessionInfo.IsSessionComplete();
}

void
VCMFrameBuffer::Reset()
{
    _length = 0;
    _timeStamp = 0;
    _sessionInfo.Reset();
    _frameCounted = false;
    _payloadType = 0;
    _nackCount = 0;
    _latestPacketTimeMs = -1;
    _state = kStateFree;
    VCMEncodedFrame::Reset();
}

// Makes sure the session contains a decodable stream.
void
VCMFrameBuffer::MakeSessionDecodable()
{
    WebRtc_Word32 retVal = _sessionInfo.MakeSessionDecodable(_buffer);
    // update length
    _length -= retVal;
}

// Set state of frame
void
VCMFrameBuffer::SetState(VCMFrameBufferStateEnum state)
{
    if (_state == state)
    {
        return;
    }
    switch (state)
    {
    case kStateFree:
        // Reset everything
        // We can go to this state from all other states.
        // The one setting the state to free must ensure
        // that the frame is removed from the timestamp
        // ordered frame list in the jb.
        Reset();
        break;

    case kStateIncomplete:
        // we can go to this state from state kStateEmpty
        assert(_state == kStateEmpty ||
            _state == kStateDecoding);

        // Do nothing, we received a packet
        break;

    case kStateComplete:
        assert(_state == kStateEmpty ||
               _state == kStateIncomplete ||
               _state == kStateDecodable);

        break;

    case kStateEmpty:
        assert(_state == kStateFree);
        // Do nothing
        break;

    case kStateDecoding:
        // we can go to this state from state kStateComplete kStateIncomplete
        assert(_state == kStateComplete || _state == kStateIncomplete ||
               _state == kStateDecodable);
        // Transfer frame information to EncodedFrame and create any codec
        // specific information
        RestructureFrameInformation();
        break;

    case kStateDecodable:
        if (_state == kStateComplete)
        {
            // if complete, obviously decodable, keep as is.
            return;
        }
        assert(_state == kStateEmpty ||
               _state == kStateIncomplete);
        break;

    default:
        // Should never happen
        assert(!"FrameBuffer::SetState Incorrect frame buffer state as input");
        return;
    }
    _state = state;
}

void
VCMFrameBuffer::RestructureFrameInformation()
{
    PrepareForDecode();
    _frameType = ConvertFrameType(_sessionInfo.FrameType());
    _completeFrame = _sessionInfo.IsSessionComplete();
    _missingFrame = _sessionInfo.PreviousFrameLoss();
}

WebRtc_Word32
VCMFrameBuffer::ExtractFromStorage(const EncodedVideoData& frameFromStorage)
{
    _frameType = ConvertFrameType(frameFromStorage.frameType);
    _timeStamp = frameFromStorage.timeStamp;
    _payloadType = frameFromStorage.payloadType;
    _encodedWidth = frameFromStorage.encodedWidth;
    _encodedHeight = frameFromStorage.encodedHeight;
    _missingFrame = frameFromStorage.missingFrame;
    _completeFrame = frameFromStorage.completeFrame;
    _renderTimeMs = frameFromStorage.renderTimeMs;
    _codec = frameFromStorage.codec;
    if (VerifyAndAllocate(frameFromStorage.payloadSize) < 0)
    {
        return VCM_MEMORY;
    }
    memcpy(_buffer, frameFromStorage.payloadData, frameFromStorage.payloadSize);
    _length = frameFromStorage.payloadSize;
    return VCM_OK;
}

// Set counted status (as counted by JB or not)
void VCMFrameBuffer::SetCountedFrame(bool frameCounted)
{
    _frameCounted = frameCounted;
}

bool VCMFrameBuffer::GetCountedFrame()
{
    return _frameCounted;
}

// Get current state of frame
VCMFrameBufferStateEnum
VCMFrameBuffer::GetState() const
{
    return _state;
}

// Get current state of frame
VCMFrameBufferStateEnum
VCMFrameBuffer::GetState(WebRtc_UWord32& timeStamp) const
{
    timeStamp = TimeStamp();
    return GetState();
}

bool
VCMFrameBuffer::IsRetransmitted()
{
    return _sessionInfo.IsRetransmitted();
}

void
VCMFrameBuffer::PrepareForDecode()
{
    _length = _sessionInfo.PrepareForDecode(_buffer, _codec);
}

}
