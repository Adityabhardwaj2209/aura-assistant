/* Mono audio capture for the voice page. Capture is enabled by the user's mic button. */
class AuraCapture extends AudioWorkletProcessor {
  constructor(){super();this.buffer=new Float32Array(2048);this.offset=0;}
  process(inputs){
    const channels=inputs[0];
    if(!channels?.length)return true;
    for(let i=0;i<channels[0].length;i++){
      let sum=0;for(const c of channels)sum+=c[i]||0;
      this.buffer[this.offset++]=sum/channels.length;
      if(this.offset===this.buffer.length){
        this.port.postMessage(this.buffer,[this.buffer.buffer]);
        this.buffer=new Float32Array(2048);this.offset=0;
      }
    }
    return true;
  }
}
registerProcessor('aura-capture',AuraCapture);
